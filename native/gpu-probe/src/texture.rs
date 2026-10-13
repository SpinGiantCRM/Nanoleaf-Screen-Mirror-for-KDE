//! Exact encoded RGB8 sampling from a GPU texture. No full-frame upload here.
use crate::ReadbackReset;
use anyhow::{ensure, Result};
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
            usage: wgpu::BufferUsages::STORAGE,
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
    /// Diagnostic oracle only. Full-frame readback is not the normal sample path.
    pub fn diagnostic_rgb(&self, texture: &wgpu::Texture) -> Result<Vec<u8>> {
        ensure!(
            texture.width() == self.width && texture.height() == self.height,
            "Diagnostic size mismatch"
        );
        ensure!(
            texture.usage().contains(wgpu::TextureUsages::COPY_SRC),
            "Diagnostic readback not enabled for this texture"
        );
        let stride = (self.width * 4).div_ceil(256) * 256;
        let size = u64::from(stride) * u64::from(self.height);
        ensure!(size <= 128 * 1024 * 1024, "Diagnostic frame size limit");
        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Diagnostic frame readback only"),
            size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut encoder = self.device.create_command_encoder(&Default::default());
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(stride),
                    rows_per_image: Some(self.height),
                },
            },
            wgpu::Extent3d {
                width: self.width,
                height: self.height,
                depth_or_array_layers: 1,
            },
        );
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
        let mut rgb = Vec::with_capacity(self.width as usize * self.height as usize * 3);
        for row in data.chunks_exact(stride as usize) {
            for pixel in row[..self.width as usize * 4].as_chunks::<4>().0 {
                if pixel[3] == 0 {
                    rgb.extend_from_slice(&[0; 3]);
                } else if texture.format() == wgpu::TextureFormat::Bgra8Unorm {
                    rgb.extend_from_slice(&[pixel[2], pixel[1], pixel[0]]);
                } else {
                    rgb.extend_from_slice(&pixel[..3]);
                }
            }
        }
        drop(data);
        drop(reset);
        Ok(rgb)
    }
}
