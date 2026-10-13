//! Experimental real Vulkan compute. No capture permission, USB or user config.
//! Only explicit SDR RGB8 is accepted; no DMA-BUF/zero-copy/HDR claims.
use anyhow::{ensure, Context, Result};
use nanoleaf_core::sampling::{SdrSampler, ZoneRect, ZoneSample};
use std::{
    future::Future,
    sync::{mpsc, Arc},
    task::{Poll, Wake, Waker},
    time::{Duration, Instant},
};
use wgpu::util::DeviceExt;
struct ThreadWake(std::thread::Thread);
struct ReadbackReset<'a>(&'a wgpu::Buffer);
impl Drop for ReadbackReset<'_> {
    fn drop(&mut self) {
        self.0.unmap();
    }
}
impl Wake for ThreadWake {
    fn wake(self: Arc<Self>) {
        self.0.unpark();
    }
}
fn wait<T>(future: impl Future<Output = T>) -> T {
    let waker = Waker::from(Arc::new(ThreadWake(std::thread::current())));
    let mut context = std::task::Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::park_timeout(Duration::from_millis(100)),
        }
    }
}
pub struct VulkanSampler {
    pub adapter: wgpu::AdapterInfo,
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipeline: wgpu::ComputePipeline,
    image: wgpu::Buffer,
    output: wgpu::Buffer,
    readback: wgpu::Buffer,
    group: wgpu::BindGroup,
    width: usize,
    height: usize,
    stride: usize,
    count: usize,
    pixels_per_zone: Vec<u64>,
}
impl VulkanSampler {
    pub fn new(width: usize, height: usize, stride: usize, zones: &[ZoneRect]) -> Result<Self> {
        ensure!(
            width > 0
                && height > 0
                && width <= 16384
                && height <= 16384
                && stride >= width.checked_mul(3).context("Row overflow")?,
            "Invalid SDR layout"
        );
        let bytes = stride.checked_mul(height).context("Frame overflow")?;
        ensure!(
            bytes <= 128 * 1024 * 1024 && !zones.is_empty() && zones.len() <= 512,
            "Probe size/count limit"
        );
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::VULKAN,
            ..wgpu::InstanceDescriptor::new_without_display_handle()
        });
        let adapter = wait(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
            ..Default::default()
        }))?;
        let info = adapter.get_info();
        ensure!(
            info.backend == wgpu::Backend::Vulkan && info.device_type != wgpu::DeviceType::Cpu,
            "Hardware Vulkan is required; software results are not GPU benchmarks"
        );
        let (device, queue) = wait(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("Nanoleaf histogram prototype"),
            ..Default::default()
        }))?;
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Exact integer zone histogram"),
            source: wgpu::ShaderSource::Wgsl(include_str!("zones.wgsl").into()),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("Single-strip zone sampling"),
            layout: None,
            module: &shader,
            entry_point: Some("sample"),
            compilation_options: Default::default(),
            cache: None,
        });
        let image = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("SDR RGB8 upload"),
            size: bytes.div_ceil(4) as u64 * 4,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut rects = Vec::new();
        let mut pixels_per_zone = Vec::new();
        for z in zones {
            let x = z.x.clamp(0, width as i64) as u32;
            let y = z.y.clamp(0, height as i64) as u32;
            let w = z.width.max(0).min(width as i64 - i64::from(x)) as u32;
            let h = z.height.max(0).min(height as i64 - i64::from(y)) as u32;
            pixels_per_zone.push(u64::from(w) * u64::from(h));
            for v in [x, y, w, h] {
                rects.extend_from_slice(&v.to_le_bytes());
            }
        }
        let zones_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("Clipped zones"),
            contents: &rects,
            usage: wgpu::BufferUsages::STORAGE,
        });
        let mut params = Vec::new();
        for value in [
            width as u32,
            height as u32,
            stride as u32,
            zones.len() as u32,
        ] {
            params.extend_from_slice(&value.to_le_bytes());
        }
        let parameters = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("Frame geometry"),
            contents: &params,
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let size = zones.len() as u64 * 768 * 4;
        let output = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Zone histograms"),
            size,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Small histogram readback"),
            size,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("Single frame zones"),
            layout: &pipeline.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: image.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: zones_buffer.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: output.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: parameters.as_entire_binding(),
                },
            ],
        });
        Ok(Self {
            adapter: info,
            device,
            queue,
            pipeline,
            image,
            output,
            readback,
            group,
            width,
            height,
            stride,
            count: zones.len(),
            pixels_per_zone,
        })
    }
    pub fn sample(&self, data: &[u8]) -> Result<(Vec<ZoneSample>, serde_json::Value)> {
        ensure!(
            data.len() == self.stride * self.height,
            "Expected explicit full SDR RGB8 rows, including padding"
        );
        let total = Instant::now();
        let mut padded = Vec::new();
        let upload = if data.len().is_multiple_of(4) {
            data
        } else {
            padded.extend_from_slice(data);
            padded.resize(data.len().div_ceil(4) * 4, 0);
            &padded
        };
        self.queue.write_buffer(&self.image, 0, upload);
        let upload_ms = total.elapsed().as_secs_f64() * 1000.0;
        let submitted = Instant::now();
        let mut encoder = self.device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("Vulkan histogram dispatch"),
                ..Default::default()
            });
            pass.set_pipeline(&self.pipeline);
            pass.set_bind_group(0, &self.group, &[]);
            pass.dispatch_workgroups(self.count as u32, 1, 1);
        }
        encoder.copy_buffer_to_buffer(
            &self.output,
            0,
            &self.readback,
            0,
            self.count as u64 * 768 * 4,
        );
        let index = self.queue.submit([encoder.finish()]);
        let (tx, rx) = mpsc::sync_channel(1);
        self.readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = tx.send(result);
            });
        let reset = ReadbackReset(&self.readback);
        self.device.poll(wgpu::PollType::Wait {
            submission_index: Some(index),
            timeout: Some(Duration::from_secs(2)),
        })?;
        rx.recv_timeout(Duration::from_secs(2))??;
        let synchronized_ms = submitted.elapsed().as_secs_f64() * 1000.0;
        let mapped = self.readback.slice(..).get_mapped_range()?;
        let sampler = SdrSampler::default();
        let mut samples = Vec::new();
        for (index, zone) in mapped.as_chunks::<3072>().0.iter().enumerate() {
            let mut counts = [[0_u64; 256]; 3];
            for (i, value) in zone.as_chunks::<4>().0.iter().enumerate() {
                counts[i / 256][i % 256] = u32::from_le_bytes(*value) as u64;
            }
            let sample = sampler.sample_histograms(&counts)?;
            ensure!(
                sample.pixel_count == self.pixels_per_zone[index],
                "Incomplete GPU zone histogram"
            );
            samples.push(sample);
        }
        drop(mapped);
        drop(reset);
        Ok((
            samples,
            serde_json::json!({"upload_copy_ms":upload_ms,"submission_compute_readback_ms":synchronized_ms,"total_ms":total.elapsed().as_secs_f64()*1000.0,"uploaded_bytes":self.image.size(),"readback_bytes":self.readback.size(),"width":self.width,"height":self.height}),
        ))
    }
}

mod texture;
pub use texture::TextureSampler;
