//! Narrow Linux Vulkan interop boundary. The app/colour crates remain safe Rust.
//! Capture buffers stay dequeued until GPU work and foreign ownership release
//! finish. Packed 8-bit, one memory plane, implicit sync only for this prototype.
use anyhow::{ensure, Context, Result};
use ash::vk;
use pipewire::{buffer::Buffer, spa};
use std::{collections::HashMap, os::unix::fs::MetadataExt};
use std::{
    os::fd::{AsRawFd, BorrowedFd, FromRawFd, OwnedFd},
    time::{Duration, Instant},
};

pub fn create_device(adapter: &wgpu::Adapter) -> Result<(wgpu::Device, wgpu::Queue)> {
    let features = wgpu::Features::VULKAN_EXTERNAL_MEMORY_DMA_BUF;
    ensure!(
        adapter.features().contains(features),
        "Vulkan DMA-BUF feature unavailable"
    );
    // SAFETY: The guard is borrowed, never destroyed or used after its adapter.
    let hal =
        unsafe { adapter.as_hal::<wgpu::hal::api::Vulkan>() }.context("Not a Vulkan adapter")?;
    let instance = hal.shared_instance().raw_instance();
    // SAFETY: Physical device belongs to the guarded instance.
    let supported =
        unsafe { instance.enumerate_device_extension_properties(hal.raw_physical_device()) }?;
    ensure!(
        supported.iter().any(|e| e
            .extension_name_as_c_str()
            .is_ok_and(|n| n == ash::ext::queue_family_foreign::NAME)),
        "Foreign queue ownership unsupported"
    );
    let mut extensions = hal.required_device_extensions(features);
    if !extensions.contains(&ash::ext::queue_family_foreign::NAME) {
        extensions.push(ash::ext::queue_family_foreign::NAME);
    }
    // SAFETY: Same physical device/instance; no resource mutation.
    let families =
        unsafe { instance.get_physical_device_queue_family_properties(hal.raw_physical_device()) };
    let family = families
        .iter()
        .position(|f| {
            f.queue_count > 0
                && f.queue_flags
                    .contains(vk::QueueFlags::GRAPHICS | vk::QueueFlags::COMPUTE)
        })
        .context("No graphics/compute queue")? as u32;
    let queues = [vk::DeviceQueueCreateInfo::default()
        .queue_family_index(family)
        .queue_priorities(&[1.0])];
    let pointers: Vec<_> = extensions.iter().map(|e| e.as_ptr()).collect();
    let mut physical_features = hal.physical_device_features(&extensions, features);
    let info = physical_features.add_to_device_create(
        vk::DeviceCreateInfo::default()
            .queue_create_infos(&queues)
            .enabled_extension_names(&pointers),
    );
    // SAFETY: Extensions were enumerated; feature chain comes from this adapter.
    let raw = unsafe { instance.create_device(hal.raw_physical_device(), &info, None) }?;
    let limits = wgpu::Limits::default();
    // SAFETY: Exact physical device, queue family, extensions, limits and features.
    // Ownership transfers to HAL on success. Cleanup below handles failure.
    let opened = match unsafe {
        hal.device_from_raw(
            raw.clone(),
            None,
            &extensions,
            features,
            &limits,
            &wgpu::MemoryHints::MemoryUsage,
            family,
            0,
        )
    } {
        Ok(device) => device,
        Err(error) => {
            // SAFETY: Creation failed before any work/resource reached this device.
            unsafe { raw.destroy_device(None) };
            return Err(error.into());
        }
    };
    drop(hal);
    let desc = wgpu::DeviceDescriptor {
        label: Some("Nanoleaf shared-frame Vulkan"),
        required_features: features,
        required_limits: limits,
        memory_hints: wgpu::MemoryHints::MemoryUsage,
        ..Default::default()
    };
    // SAFETY: OpenDevice was created using this exact adapter and feature set.
    Ok(unsafe { adapter.create_device_from_hal::<wgpu::hal::api::Vulkan>(opened, &desc) }?)
}

pub fn modifiers(device: &wgpu::Device, format: wgpu::TextureFormat) -> Result<Vec<u64>> {
    let format = vk_format(format)?;
    // SAFETY: Borrowed HAL guard, no destruction or concurrent queue use.
    let hal = unsafe { device.as_hal::<wgpu::hal::api::Vulkan>() }.context("Not Vulkan")?;
    let instance = hal.shared_instance().raw_instance();
    let physical = hal.raw_physical_device();
    let mut list = vk::DrmFormatModifierPropertiesListEXT::default();
    let mut props = vk::FormatProperties2::default().push_next(&mut list);
    // SAFETY: Extension feature is enabled; output chain remains alive.
    unsafe { instance.get_physical_device_format_properties2(physical, format, &mut props) };
    let mut entries = vec![
        vk::DrmFormatModifierPropertiesEXT::default();
        list.drm_format_modifier_count as usize
    ];
    list.p_drm_format_modifier_properties = entries.as_mut_ptr();
    let mut props = vk::FormatProperties2::default().push_next(&mut list);
    // SAFETY: Correct allocated count; vector/chain stable for duration of call.
    unsafe { instance.get_physical_device_format_properties2(physical, format, &mut props) };
    entries.truncate((list.drm_format_modifier_count as usize).min(entries.len()));
    let mut result = Vec::new();
    for entry in entries {
        if entry.drm_format_modifier_plane_count != 1
            || !entry
                .drm_format_modifier_tiling_features
                .contains(vk::FormatFeatureFlags::SAMPLED_IMAGE)
        {
            continue;
        }
        let mut external = vk::PhysicalDeviceExternalImageFormatInfo::default()
            .handle_type(vk::ExternalMemoryHandleTypeFlags::DMA_BUF_EXT);
        let mut modifier = vk::PhysicalDeviceImageDrmFormatModifierInfoEXT::default()
            .drm_format_modifier(entry.drm_format_modifier)
            .sharing_mode(vk::SharingMode::EXCLUSIVE);
        let info = vk::PhysicalDeviceImageFormatInfo2::default()
            .format(format)
            .ty(vk::ImageType::TYPE_2D)
            .tiling(vk::ImageTiling::DRM_FORMAT_MODIFIER_EXT)
            .usage(vk::ImageUsageFlags::SAMPLED | vk::ImageUsageFlags::TRANSFER_SRC)
            .push_next(&mut external)
            .push_next(&mut modifier);
        let mut ext = vk::ExternalImageFormatProperties::default();
        let mut properties = vk::ImageFormatProperties2::default().push_next(&mut ext);
        // SAFETY: Capability query uses valid owned extension chains only.
        if unsafe {
            instance.get_physical_device_image_format_properties2(physical, &info, &mut properties)
        }
        .is_ok()
            && ext
                .external_memory_properties
                .external_memory_features
                .contains(vk::ExternalMemoryFeatureFlags::IMPORTABLE)
        {
            result.push(entry.drm_format_modifier);
        }
    }
    result.sort_unstable();
    result.dedup();
    Ok(result)
}
fn vk_format(format: wgpu::TextureFormat) -> Result<vk::Format> {
    match format {
        wgpu::TextureFormat::Bgra8Unorm => Ok(vk::Format::B8G8R8A8_UNORM),
        wgpu::TextureFormat::Rgba8Unorm => Ok(vk::Format::R8G8B8A8_UNORM),
        _ => anyhow::bail!("Only packed non-sRGB 8-bit textures are supported"),
    }
}

#[repr(C)]
struct ExportSync {
    flags: u32,
    fd: i32,
}
fn wait_producer(fd: BorrowedFd<'_>) -> Result<()> {
    let mut sync = ExportSync { flags: 1, fd: -1 }; // DMA_BUF_SYNC_READ
                                                    // Linux UAPI _IOWR('b', 2, sizeof(dma_buf_export_sync_file)).
                                                    // SAFETY: live borrowed DMA-BUF FD; writable correctly sized UAPI struct.
    let result =
        unsafe { libc::ioctl(fd.as_raw_fd(), 0xc008_6202_u64 as libc::c_ulong, &mut sync) };
    ensure!(
        result == 0 && sync.fd >= 0,
        "DMA-BUF producer fence export failed: {}",
        std::io::Error::last_os_error()
    );
    // SAFETY: Successful ioctl returned a fresh, exclusively owned sync-file FD.
    let fence = unsafe { OwnedFd::from_raw_fd(sync.fd) };
    let mut poll = libc::pollfd {
        fd: fence.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    let started = Instant::now();
    loop {
        // SAFETY: One valid pollfd, valid sync-file FD; timeout is bounded.
        let result = unsafe {
            libc::poll(
                &mut poll,
                1,
                2000_i32.saturating_sub(started.elapsed().as_millis().min(2000) as i32),
            )
        };
        if result < 0
            && std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted
            && started.elapsed() < Duration::from_secs(2)
        {
            continue;
        }
        ensure!(
            result > 0
                && poll.revents & libc::POLLIN != 0
                && poll.revents & (libc::POLLERR | libc::POLLNVAL) == 0,
            "DMA-BUF producer fence not ready"
        );
        break;
    }
    Ok(())
}

/// Read exact encoded pixels while the imported texture is exclusively owned.
/// No texture/device handles are exposed or can escape to the caller.
pub struct RegionReader<'a> {
    sampler: &'a nanoleaf_vulkan_probe::TextureSampler,
    texture: &'a wgpu::Texture,
    bytes: usize,
    reads: usize,
    full: Option<Vec<u8>>,
    edges: Option<Vec<Vec<u8>>>,
    transfers: usize,
}
impl RegionReader<'_> {
    fn edges(&mut self) -> Result<()> {
        if self.edges.is_some() || self.full.is_some() {
            return Ok(());
        }
        let (w, h) = (self.texture.width(), self.texture.height());
        let edges = self.sampler.regions_rgb(
            self.texture,
            &[
                [0, 0, w, 1],
                [0, h - 1, w, 1],
                [0, 0, 1, h],
                [w - 1, 0, 1, h],
            ],
        )?;
        ensure!(edges.len() == 4, "Incomplete edge readback batch");
        self.bytes += edges.iter().map(Vec::len).sum::<usize>();
        self.reads += 4;
        self.transfers += 1;
        self.edges = Some(edges);
        Ok(())
    }
    fn region(&mut self, rect: [u32; 4]) -> Result<Vec<u8>> {
        // Black screens/wide bars can require hundreds of detector reads. After
        // eight sparse copies, read once and run the SAME ordered CPU analysis.
        // This bounds GPU round trips without skipping or approximating pixels.
        if self.reads >= 8 && self.full.is_none() {
            let rgb = self.sampler.diagnostic_rgb(self.texture)?;
            self.bytes += rgb.len();
            self.full = Some(rgb);
            self.transfers += 1;
        }
        if let Some(rgb) = &self.full {
            let width = self.texture.width() as usize;
            ensure!(
                rect[0]
                    .checked_add(rect[2])
                    .is_some_and(|r| r <= self.texture.width())
                    && rect[1]
                        .checked_add(rect[3])
                        .is_some_and(|b| b <= self.texture.height()),
                "Invalid analysis rectangle"
            );
            let mut result = Vec::with_capacity(rect[2] as usize * rect[3] as usize * 3);
            for y in rect[1]..rect[1] + rect[3] {
                let i = (y as usize * width + rect[0] as usize) * 3;
                result.extend_from_slice(&rgb[i..i + rect[2] as usize * 3]);
            }
            return Ok(result);
        }
        let result = self.sampler.region_rgb(self.texture, rect)?;
        self.reads += 1;
        self.transfers += 1;
        self.bytes += result.len();
        Ok(result)
    }
    pub fn row(&mut self, y: u32) -> Result<Vec<u8>> {
        self.edges()?;
        if let Some(edges) = &self.edges {
            if y == 0 {
                return Ok(edges[0].clone());
            }
            if y == self.texture.height() - 1 {
                return Ok(edges[1].clone());
            }
        }
        self.region([0, y, self.texture.width(), 1])
    }
    pub fn column(&mut self, x: u32, top: u32, bottom: u32) -> Result<Vec<u8>> {
        ensure!(bottom > top, "Invalid analysis column");
        self.edges()?;
        if let Some(edges) = &self.edges {
            let edge = if x == 0 {
                Some(&edges[2])
            } else if x == self.texture.width() - 1 {
                Some(&edges[3])
            } else {
                None
            };
            if let Some(edge) = edge {
                return Ok(edge
                    .get(top as usize * 3..bottom as usize * 3)
                    .context("Invalid analysis column")?
                    .to_vec());
            }
        }
        self.region([x, top, 1, bottom - top])
    }
}
/// A GPU sampler that exposes only colour statistics and optional diagnostic
/// bytes. Imported textures cannot escape the dequeued PipeWire buffer lifetime.
pub struct DmaSampler {
    sampler: nanoleaf_vulkan_probe::TextureSampler,
    cache: HashMap<FrameKey, CachedFrame>,
}
#[derive(Clone, Copy, Hash, PartialEq, Eq)]
struct FrameKey {
    inode: u64,
    dev: u64,
    width: u32,
    height: u32,
    packing: u32,
    modifier: u64,
    stride: u64,
    offset: u64,
}
struct CachedFrame {
    texture: wgpu::Texture,
    image: vk::Image,
    raw_device: ash::Device,
    family: u32,
}

pub struct SampledFrame {
    pub samples: Vec<nanoleaf_core::sampling::ZoneSample>,
    pub diagnostic_rgb: Option<Vec<u8>>,
    pub timings: serde_json::Value,
}
impl DmaSampler {
    pub fn new(
        device: wgpu::Device,
        queue: wgpu::Queue,
        width: u32,
        height: u32,
        zones: &[nanoleaf_core::sampling::ZoneRect],
    ) -> Result<Self> {
        Ok(Self {
            sampler: nanoleaf_vulkan_probe::TextureSampler::new(
                device, queue, width, height, zones,
            )?,
            cache: HashMap::new(),
        })
    }
    pub fn plan_sample<T>(
        &mut self,
        buffer: &mut Buffer<'_>,
        format: spa::param::video::VideoInfoRaw,
        diagnostic: bool,
        plan: impl FnOnce(&mut RegionReader<'_>) -> Result<(Vec<nanoleaf_core::sampling::ZoneRect>, T)>,
    ) -> Result<(SampledFrame, T)> {
        let device = self.sampler.device().clone();
        let queue = self.sampler.queue().clone();
        let sampler = &mut self.sampler;
        let started = Instant::now();
        let mut stages = serde_json::Value::Null;
        let (mut sampled, context) = with_texture(
            &mut self.cache,
            &mut stages,
            &device,
            &queue,
            buffer,
            format,
            |texture| {
                let (zones, context, bytes, transfers, full) = {
                    let mut reader = RegionReader {
                        sampler,
                        texture,
                        bytes: 0,
                        reads: 0,
                        full: None,
                        edges: None,
                        transfers: 0,
                    };
                    let (zones, context) = plan(&mut reader)?;
                    (zones, context, reader.bytes, reader.transfers, reader.full)
                };
                sampler.set_zones(&zones)?;
                let diagnostic_rgb = if diagnostic {
                    Some(match full {
                        Some(rgb) => rgb,
                        None => sampler.diagnostic_rgb(texture)?,
                    })
                } else {
                    None
                };
                let (samples, mut timings) = sampler.sample(texture)?;
                timings["analysis_rgb_bytes"] = serde_json::json!(bytes);
                timings["analysis_transfer_batches"] = serde_json::json!(transfers);
                Ok((
                    SampledFrame {
                        samples,
                        diagnostic_rgb,
                        timings,
                    },
                    context,
                ))
            },
        )?;
        sampled.timings["interop"] = stages;
        sampled.timings["complete_frame_ms"] =
            serde_json::json!(started.elapsed().as_secs_f64() * 1000.0);
        Ok((sampled, context))
    }
    pub fn sample(
        &mut self,
        buffer: &mut Buffer<'_>,
        format: spa::param::video::VideoInfoRaw,
        diagnostic: bool,
    ) -> Result<SampledFrame> {
        let sampler = &self.sampler;
        let started = Instant::now();
        let mut stages = serde_json::Value::Null;
        let mut result = with_texture(
            &mut self.cache,
            &mut stages,
            sampler.device(),
            sampler.queue(),
            buffer,
            format,
            |texture| {
                let diagnostic_rgb = if diagnostic {
                    Some(sampler.diagnostic_rgb(texture)?)
                } else {
                    None
                };
                // Sampling follows any diagnostic COPY_SRC operation, restoring the
                // SHADER_READ_ONLY state expected by the foreign release barrier.
                let (samples, timings) = sampler.sample(texture)?;
                Ok(SampledFrame {
                    samples,
                    diagnostic_rgb,
                    timings,
                })
            },
        )?;
        result.timings["interop"] = stages;
        result.timings["complete_frame_ms"] =
            serde_json::json!(started.elapsed().as_secs_f64() * 1000.0);
        result.timings["cached_images"] = serde_json::json!(self.cache.len());
        Ok(result)
    }
}
// Private: only the synchronous sampler above receives this borrowed texture.
fn with_texture<T>(
    cache: &mut HashMap<FrameKey, CachedFrame>,
    stages: &mut serde_json::Value,
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    buffer: &mut Buffer<'_>,
    format: spa::param::video::VideoInfoRaw,
    run: impl FnOnce(&wgpu::Texture) -> Result<T>,
) -> Result<T> {
    let started = Instant::now();
    let width = format.size().width;
    let height = format.size().height;
    ensure!(
        width > 0 && height > 0 && width <= 16384 && height <= 16384,
        "DMA-BUF dimensions invalid"
    );
    ensure!(
        format
            .flags()
            .contains(spa::param::video::VideoFlags::MODIFIER),
        "DMA-BUF modifier was not negotiated"
    );
    let texture_format = match format.format() {
        spa::param::video::VideoFormat::BGRA => wgpu::TextureFormat::Bgra8Unorm,
        spa::param::video::VideoFormat::RGBA => wgpu::TextureFormat::Rgba8Unorm,
        _ => anyhow::bail!("Unsupported DMA-BUF packing"),
    };
    ensure!(
        !format
            .flags()
            .contains(spa::param::video::VideoFlags::PREMULTIPLIED_ALPHA),
        "Premultiplied DMA-BUF requires verified alpha conversion"
    );
    let planes = buffer.datas_mut();
    ensure!(
        planes.len() == 1 && planes[0].type_() == spa::buffer::DataType::DmaBuf,
        "One DMA-BUF plane with implicit synchronization required"
    );
    let data = &planes[0];
    ensure!(
        data.fd() >= 0
            && !data.as_raw().chunk.is_null()
            && data.chunk().stride() > 0
            && !data
                .chunk()
                .flags()
                .contains(spa::buffer::ChunkFlags::CORRUPTED),
        "Invalid DMA-BUF layout/chunk"
    );
    // SAFETY: Data's FD is owned by the dequeued Buffer, alive until this call ends.
    let borrowed = unsafe { BorrowedFd::borrow_raw(data.fd()) };
    wait_producer(borrowed)?;
    let fence_ms = started.elapsed().as_secs_f64() * 1000.0;
    let file = std::fs::File::from(borrowed.try_clone_to_owned()?);
    let metadata = file.metadata()?;
    let stride = data.chunk().stride() as u64;
    let offset = u64::from(data.as_raw().mapoffset)
        .checked_add(u64::from(data.chunk().offset()))
        .context("DMA-BUF offset overflow")?;
    let key = FrameKey {
        inode: metadata.ino(),
        dev: metadata.dev(),
        width,
        height,
        packing: format.format().as_raw(),
        modifier: format.modifier(),
        stride,
        offset,
    };
    let cached = cache.contains_key(&key);
    let import_started = Instant::now();
    if !cached {
        // A held Vulkan allocation keeps the DMA-BUF inode alive, so numeric FD
        // reuse cannot alias a stale cached image. Bound to four compositor buffers.
        if cache.len() >= 4 {
            cache.clear();
        }
        let duplicate: OwnedFd = file.into();

        let size = wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        };
        let desc = wgpu::TextureDescriptor {
            label: Some("Imported screen frame"),
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: texture_format,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        };
        let hal_desc = wgpu::hal::TextureDescriptor {
            label: desc.label,
            size,
            mip_level_count: 1,
            sample_count: 1,
            dimension: desc.dimension,
            format: texture_format,
            usage: wgpu::TextureUses::RESOURCE | wgpu::TextureUses::COPY_SRC,
            memory_flags: wgpu::hal::MemoryFlags::empty(),
            view_formats: vec![],
        };
        // SAFETY: Same guarded device. Negotiated format/layout and live DMA-BUF FD.
        let hal = unsafe { device.as_hal::<wgpu::hal::api::Vulkan>() }.context("Not Vulkan")?;
        // SAFETY: HAL consumes only our duplicate; dimensions/format/modifier/plane
        // stride and offset are taken from this dequeued negotiated frame.
        let imported = unsafe {
            hal.texture_from_dmabuf_fd(duplicate, &hal_desc, format.modifier(), stride, offset)
        }?;
        let raw_device = hal.raw_device().clone();
        let family = hal.queue_family_index();
        // SAFETY: We only reference the live image; HAL retains ownership until wrapping.
        let image = unsafe { imported.raw_handle() };
        drop(hal);
        if let Err(error) = transfer(device, queue, &raw_device, family, image, true) {
            // SAFETY: Transfer never submitted work successfully, or waited for completion.
            let hal = unsafe { device.as_hal::<wgpu::hal::api::Vulkan>() }
                .context("Lost Vulkan device")?;
            // SAFETY: Unwrapped texture belongs to this device, never reached wgpu and is idle.
            unsafe { wgpu::hal::Device::destroy_texture(&*hal, imported) };
            return Err(error);
        }
        // SAFETY: Contents are producer-initialized, fence waited, ownership acquired
        // and layout explicitly transitioned to SHADER_READ_ONLY_OPTIMAL (=RESOURCE).
        let texture = unsafe {
            device.create_texture_from_hal::<wgpu::hal::api::Vulkan>(
                imported,
                &desc,
                wgpu::TextureUses::RESOURCE,
            )
        };
        cache.insert(
            key,
            CachedFrame {
                texture,
                image,
                raw_device,
                family,
            },
        );
    }
    let import_ms = import_started.elapsed().as_secs_f64() * 1000.0;
    let frame = cache
        .get(&key)
        .context("Missing imported frame cache entry")?;
    let acquire_started = Instant::now();
    if cached {
        transfer(
            device,
            queue,
            &frame.raw_device,
            frame.family,
            frame.image,
            true,
        )?;
    }
    let acquire_ms = acquire_started.elapsed().as_secs_f64() * 1000.0;
    let result = run(&frame.texture);
    // Do not return a PipeWire buffer while a failed callback still has GPU work.
    if device
        .poll(wgpu::PollType::Wait {
            submission_index: None,
            timeout: Some(Duration::from_secs(2)),
        })
        .is_err()
    {
        // This executable is capture-only. Kernel teardown is safer than letting
        // Buffer::drop requeue memory that may still be in use after a GPU hang.
        eprintln!("GPU completion failed; terminating the isolated capture probe");
        std::process::exit(2);
    }
    let release_started = Instant::now();
    if transfer(
        device,
        queue,
        &frame.raw_device,
        frame.family,
        frame.image,
        false,
    )
    .is_err()
    {
        eprintln!("Could not release foreign GPU ownership; terminating capture probe");
        std::process::exit(2);
    }
    let release_ms = release_started.elapsed().as_secs_f64() * 1000.0;
    *stages = serde_json::json!({"producer_fence_ms":fence_ms,"import_or_cache_ms":import_ms,"cache_hit":cached,"acquire_ms":acquire_ms,"release_ms":release_ms});
    result
}

fn transfer(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    raw: &ash::Device,
    family: u32,
    image: vk::Image,
    acquire: bool,
) -> Result<()> {
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("Foreign screen buffer ownership"),
    });
    // SAFETY: The callback only records a Vulkan barrier into this encoder's
    // currently open command buffer. It does not destroy/retain raw handles.
    // The image remains owned and alive through the subsequent completed submit.
    unsafe {
        encoder.as_hal_mut::<wgpu::hal::api::Vulkan, _, _>(|encoder| {
            let encoder = encoder.expect("Vulkan command encoder");
            // SAFETY: Borrow only for recording; neither destroy nor retain handle.
            let command = encoder.raw_handle();
            let range = vk::ImageSubresourceRange::default()
                .aspect_mask(vk::ImageAspectFlags::COLOR)
                .level_count(1)
                .layer_count(1);
            let barrier = if acquire {
                vk::ImageMemoryBarrier::default()
                    .old_layout(vk::ImageLayout::GENERAL)
                    .new_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
                    .src_queue_family_index(vk::QUEUE_FAMILY_FOREIGN_EXT)
                    .dst_queue_family_index(family)
                    .dst_access_mask(vk::AccessFlags::SHADER_READ)
            } else {
                vk::ImageMemoryBarrier::default()
                    .old_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)
                    .new_layout(vk::ImageLayout::GENERAL)
                    .src_queue_family_index(family)
                    .dst_queue_family_index(vk::QUEUE_FAMILY_FOREIGN_EXT)
                    .src_access_mask(vk::AccessFlags::SHADER_READ)
            }
            .image(image)
            .subresource_range(range);
            // SAFETY: External producer is complete; image layout, plane and paired
            // ownership states are checked by this module. No GPU use is pending
            // before release. The guarded encoder is recording and on this device.
            raw.cmd_pipeline_barrier(
                command,
                vk::PipelineStageFlags::ALL_COMMANDS,
                vk::PipelineStageFlags::ALL_COMMANDS,
                vk::DependencyFlags::empty(),
                &[],
                &[],
                &[barrier],
            );
        });
    }
    // Submit through wgpu, which serializes access to the Vulkan queue. Never
    // call raw vkQueueSubmit alongside possible wgpu submissions.
    let index = queue.submit([encoder.finish()]);
    if device
        .poll(wgpu::PollType::Wait {
            submission_index: Some(index),
            timeout: Some(Duration::from_secs(2)),
        })
        .is_err()
    {
        eprintln!("Vulkan ownership transfer failed; terminating isolated capture probe");
        std::process::exit(2);
    }
    Ok(())
}
