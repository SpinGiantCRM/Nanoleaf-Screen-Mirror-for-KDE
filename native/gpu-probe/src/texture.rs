//! Exact encoded RGB8 sampling from a GPU texture. No full-frame upload here.
use crate::ReadbackReset;
use anyhow::{ensure, Context, Result};
use nanoleaf_core::sampling::{SdrSampler, ZoneRect, ZoneSample};
use std::{
    sync::mpsc,
    time::{Duration, Instant},
};
use wgpu::util::DeviceExt;
pub struct TextureSampler {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipeline: wgpu::ComputePipeline,
    zones: wgpu::Buffer,
    parameters: wgpu::Buffer,
    output: wgpu::Buffer,
    readback: wgpu::Buffer,
    width: u32,
    height: u32,
    pixels: Vec<u64>,
}
impl TextureSampler {
    pub fn new(
        device: wgpu::Device,
        queue: wgpu::Queue,
        width: u32,
        height: u32,
        zones: &[ZoneRect],
    ) -> Result<Self> {
        ensure!(
            width > 0
                && height > 0
                && width <= 16384
                && height <= 16384
                && !zones.is_empty()
                && zones.len() <= 512,
            "Texture size/zone limit"
        );
        ensure!(
            width <= device.limits().max_texture_dimension_2d
                && height <= device.limits().max_texture_dimension_2d,
            "Texture exceeds device limits"
        );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Exact texture RGB8 histogram"),
            source: wgpu::ShaderSource::Wgsl(include_str!("texture.wgsl").into()),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("GPU-resident single-strip sampling"),
            layout: None,
            module: &shader,
            entry_point: Some("sample"),
            compilation_options: Default::default(),
            cache: None,
        });
        let mut rects = Vec::new();
        let mut pixels = Vec::new();
        for zone in zones {
            let x = zone.x.clamp(0, i64::from(width)) as u32;
            let y = zone.y.clamp(0, i64::from(height)) as u32;
            let w = zone.width.max(0).min(i64::from(width - x)) as u32;
            let h = zone.height.max(0).min(i64::from(height - y)) as u32;
            pixels.push(u64::from(w) * u64::from(h));
            for value in [x, y, w, h] {
                rects.extend_from_slice(&value.to_le_bytes());
            }
        }
        let zones = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("Texture zones"),
            contents: &rects,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        });
        let mut params = Vec::new();
        for value in [width, height, 0, pixels.len() as u32] {
            params.extend_from_slice(&value.to_le_bytes());
        }
        let parameters = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("Texture layout"),
            contents: &params,
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let size = pixels.len() as u64 * 3072;
        let output = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Texture histograms"),
            size,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Texture small readback"),
            size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Ok(Self {
            device,
            queue,
            pipeline,
            zones,
            parameters,
            output,
            readback,
            width,
            height,
            pixels,
        })
    }
    pub fn device(&self) -> &wgpu::Device {
        &self.device
    }
    pub fn queue(&self) -> &wgpu::Queue {
        &self.queue
    }
    pub fn sample(&self, texture: &wgpu::Texture) -> Result<(Vec<ZoneSample>, serde_json::Value)> {
        ensure!(
            texture.width() == self.width
                && texture.height() == self.height
                && matches!(
                    texture.format(),
                    wgpu::TextureFormat::Bgra8Unorm | wgpu::TextureFormat::Rgba8Unorm
                ),
            "Explicit encoded RGB8 texture required"
        );
        let started = Instant::now();
        let view = texture.create_view(&Default::default());
        let group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("Current GPU frame"),
            layout: &self.pipeline.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: self.zones.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: self.output.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: self.parameters.as_entire_binding(),
                },
            ],
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_compute_pass(&Default::default());
            pass.set_pipeline(&self.pipeline);
            pass.set_bind_group(0, &group, &[]);
            pass.dispatch_workgroups(self.pixels.len() as u32, 1, 1);
        }
        encoder.copy_buffer_to_buffer(&self.output, 0, &self.readback, 0, self.readback.size());
        let index = self.queue.submit([encoder.finish()]);
        let (tx, rx) = mpsc::sync_channel(1);
        self.readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |r| {
                let _ = tx.send(r);
            });
        let reset = ReadbackReset(&self.readback);
        self.device.poll(wgpu::PollType::Wait {
            submission_index: Some(index),
            timeout: Some(Duration::from_secs(2)),
        })?;
        rx.recv_timeout(Duration::from_secs(2))??;
        let mapped = self.readback.slice(..).get_mapped_range()?;
        let mut result = Vec::new();
        let sampler = SdrSampler::default();
        ensure!(
            mapped.len() == self.pixels.len() * 3072,
            "Incomplete texture readback"
        );
        for (i, zone) in mapped.as_chunks::<3072>().0.iter().enumerate() {
            let mut counts = [[0_u64; 256]; 3];
            for (c, bytes) in zone.as_chunks::<4>().0.iter().enumerate() {
                counts[c / 256][c % 256] = u64::from(u32::from_le_bytes(*bytes));
            }
            let sample = sampler.sample_histograms(&counts)?;
            ensure!(
                sample.pixel_count == self.pixels[i],
                "Incomplete texture histogram"
            );
            result.push(sample);
        }
        drop(mapped);
        drop(reset);
        Ok((
            result,
            serde_json::json!({"uploaded_frame_bytes":0,"readback_bytes":self.readback.size(),"compute_readback_reduce_ms":started.elapsed().as_secs_f64()*1000.0}),
        ))
    }
    pub fn set_zones(&mut self, zones: &[ZoneRect]) -> Result<()> {
        ensure!(
            zones.len() == self.pixels.len(),
            "Zone count cannot change within a stream generation"
        );
        let mut bytes = Vec::new();
        self.pixels.clear();
        for z in zones {
            let x = z.x.clamp(0, i64::from(self.width)) as u32;
            let y = z.y.clamp(0, i64::from(self.height)) as u32;
            let w = z.width.max(0).min(i64::from(self.width - x)) as u32;
            let h = z.height.max(0).min(i64::from(self.height - y)) as u32;
            self.pixels.push(u64::from(w) * u64::from(h));
            for v in [x, y, w, h] {
                bytes.extend_from_slice(&v.to_le_bytes());
            }
        }
        self.queue.write_buffer(&self.zones, 0, &bytes);
        Ok(())
    }
    /// Diagnostic oracle only. Full-frame readback is not the normal sample path.
    pub fn diagnostic_rgb(&self, texture: &wgpu::Texture) -> Result<Vec<u8>> {
        self.region_rgb(texture, [0, 0, self.width, self.height])
    }
    pub fn region_rgb(&self, texture: &wgpu::Texture, rect: [u32; 4]) -> Result<Vec<u8>> {
        self.regions_rgb(texture, &[rect])?
            .pop()
            .context("Missing region readback")
    }
    /// Exact encoded regions in one submission/map. No downscaling or float reduction.
    pub fn regions_rgb(&self, texture: &wgpu::Texture, rects: &[[u32; 4]]) -> Result<Vec<Vec<u8>>> {
        ensure!(
            texture.width() == self.width && texture.height() == self.height,
            "Diagnostic size mismatch"
        );
        ensure!(
            matches!(
                texture.format(),
                wgpu::TextureFormat::Bgra8Unorm | wgpu::TextureFormat::Rgba8Unorm
            ),
            "Explicit encoded RGB8 texture required"
        );
        ensure!(
            texture.usage().contains(wgpu::TextureUsages::COPY_SRC),
            "Diagnostic readback not enabled for this texture"
        );
        let (regions, size) = readback_layout(self.width, self.height, rects)?;
        if regions.is_empty() {
            return Ok(vec![]);
        }
        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Exact region batch readback"),
            size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        for region in &regions {
            let [x, y, width, height] = region.rect;
            encoder.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo {
                    texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d { x, y, z: 0 },
                    aspect: wgpu::TextureAspect::All,
                },
                wgpu::TexelCopyBufferInfo {
                    buffer: &readback,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: region.offset,
                        bytes_per_row: Some(region.stride),
                        rows_per_image: Some(height),
                    },
                },
                wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
            );
        }
        let index = self.queue.submit([encoder.finish()]);
        let (tx, rx) = mpsc::sync_channel(1);
        readback.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        let reset = ReadbackReset(&readback);
        self.device.poll(wgpu::PollType::Wait {
            submission_index: Some(index),
            timeout: Some(Duration::from_secs(2)),
        })?;
        rx.recv_timeout(Duration::from_secs(2))??;
        let data = readback.slice(..).get_mapped_range()?;
        let mut result = Vec::with_capacity(regions.len());
        for region in regions {
            let [_, _, width, height] = region.rect;
            let bytes = data
                .get(region.offset as usize..(region.offset + region.size) as usize)
                .context("Incomplete region readback")?;
            let mut rgb = Vec::with_capacity(width as usize * height as usize * 3);
            for row in bytes.chunks_exact(region.stride as usize) {
                for pixel in row[..width as usize * 4].as_chunks::<4>().0 {
                    if pixel[3] == 0 {
                        rgb.extend_from_slice(&[0; 3]);
                    } else if texture.format() == wgpu::TextureFormat::Bgra8Unorm {
                        rgb.extend_from_slice(&[pixel[2], pixel[1], pixel[0]]);
                    } else {
                        rgb.extend_from_slice(&pixel[..3]);
                    }
                }
            }
            result.push(rgb);
        }
        drop(data);
        drop(reset);
        Ok(result)
    }
}

struct ReadRegion {
    rect: [u32; 4],
    stride: u32,
    offset: u64,
    size: u64,
}
fn readback_layout(width: u32, height: u32, rects: &[[u32; 4]]) -> Result<(Vec<ReadRegion>, u64)> {
    ensure!(rects.len() <= 256, "Analysis region count limit");
    let mut result = Vec::with_capacity(rects.len());
    let mut offset = 0_u64;
    for &rect in rects {
        let [x, y, w, h] = rect;
        ensure!(
            w > 0
                && h > 0
                && x.checked_add(w).is_some_and(|r| r <= width)
                && y.checked_add(h).is_some_and(|b| b <= height),
            "Analysis region out of bounds"
        );
        let row = w.checked_mul(4).context("Analysis stride overflow")?;
        let stride = row
            .div_ceil(256)
            .checked_mul(256)
            .context("Analysis stride overflow")?;
        let size = u64::from(stride) * u64::from(h);
        let end = offset
            .checked_add(size)
            .context("Analysis readback overflow")?;
        ensure!(end <= 128 * 1024 * 1024, "Diagnostic frame size limit");
        result.push(ReadRegion {
            rect,
            stride,
            offset,
            size,
        });
        offset = end;
    }
    Ok((result, offset))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn region_batch_layout_is_aligned_bounded_and_never_overlaps() {
        let (regions, total) = readback_layout(
            96,
            64,
            &[
                [0, 0, 96, 1],
                [0, 63, 96, 1],
                [23, 7, 1, 41],
                [17, 13, 29, 19],
            ],
        )
        .unwrap();
        let mut end = 0;
        for r in regions {
            assert_eq!(r.offset, end);
            assert_eq!(r.offset % 256, 0);
            assert_eq!(r.stride % 256, 0);
            end += r.size;
        }
        assert_eq!(total, end);
        assert_eq!(readback_layout(96, 64, &[]).unwrap().1, 0);
        for rect in [
            [0, 0, 0, 1],
            [95, 0, 2, 1],
            [0, 63, 1, 2],
            [u32::MAX, 0, 1, 1],
        ] {
            assert!(readback_layout(96, 64, &[rect]).is_err());
        }
        assert!(readback_layout(u32::MAX, 1, &[[0, 0, u32::MAX, 1]]).is_err());
        assert!(readback_layout(16384, 16384, &[[0, 0, 16384, 16384]]).is_err());
        assert!(readback_layout(1, 1, &[[0, 0, 1, 1]; 257]).is_err());
    }
}
