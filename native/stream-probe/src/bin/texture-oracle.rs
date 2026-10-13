//! Hardware texture shader oracle. No capture permission, HID or saved frames.
#[path = "../gpu.rs"]
mod gpu;
use anyhow::{ensure, Result};
use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect};
use nanoleaf_vulkan_probe::TextureSampler;
fn main() -> Result<()> {
    let (device, queue, adapter) = gpu::prepare()?;
    let zones = [
        ZoneRect {
            x: 0,
            y: 0,
            width: 96,
            height: 64,
        },
        ZoneRect {
            x: -2,
            y: -3,
            width: 7,
            height: 5,
        },
        ZoneRect {
            x: 94,
            y: 62,
            width: 10,
            height: 10,
        },
        ZoneRect {
            x: 100,
            y: 70,
            width: 5,
            height: 5,
        },
    ];
    let mut sampler = TextureSampler::new(device, queue, 96, 64, &zones)?;
    let mut comparisons = 0;
    let mut region_comparisons = 0;
    let mut updated_zone_comparisons = 0;
    let mut results = Vec::new();
    for format in [
        wgpu::TextureFormat::Bgra8Unorm,
        wgpu::TextureFormat::Rgba8Unorm,
    ] {
        let texture = sampler.device().create_texture(&wgpu::TextureDescriptor {
            label: Some("Synthetic encoded 8-bit oracle"),
            size: wgpu::Extent3d {
                width: 96,
                height: 64,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_DST
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        for pattern in ["black", "grey", "white", "all_codes", "mixed"] {
            let mut encoded = Vec::new();
            let mut rgb = Vec::new();
            for n in 0..96 * 64_u32 {
                let value = match pattern {
                    "black" => [0; 3],
                    "grey" => [128; 3],
                    "white" => [255; 3],
                    "mixed" => {
                        if n % 96 < 48 {
                            [20, 160, 45]
                        } else {
                            [215, 10, 30]
                        }
                    }
                    _ => [
                        (n % 256) as u8,
                        ((n * 43) % 256) as u8,
                        ((n * 73) % 256) as u8,
                    ],
                };
                rgb.extend_from_slice(&value);
                if format == wgpu::TextureFormat::Bgra8Unorm {
                    encoded.extend_from_slice(&[value[2], value[1], value[0], 255]);
                } else {
                    encoded.extend_from_slice(&[value[0], value[1], value[2], 255]);
                }
            }
            sampler.queue().write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                &encoded,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(96 * 4),
                    rows_per_image: Some(64),
                },
                texture.size(),
            );
            ensure!(
                sampler.diagnostic_rgb(&texture)? == rgb,
                "Texture diagnostic conversion mismatch"
            );
            for rect in [
                [0, 0, 96, 1],
                [0, 63, 96, 1],
                [23, 7, 1, 41],
                [17, 13, 29, 19],
            ] {
                let mut expected = Vec::new();
                for y in rect[1]..rect[1] + rect[3] {
                    for x in rect[0]..rect[0] + rect[2] {
                        let i = (y as usize * 96 + x as usize) * 3;
                        expected.extend_from_slice(&rgb[i..i + 3]);
                    }
                }
                ensure!(
                    sampler.region_rgb(&texture, rect)? == expected,
                    "Region extraction changed encoded pixels"
                );
                region_comparisons += 1;
            }
            let view = SdrRgb8Frame::new(&rgb, 96, 64, 96 * 3)?;
            let cpu = SdrSampler::default();
            let (samples, timings) = sampler.sample(&texture)?;
            for (actual, &zone) in samples.iter().zip(&zones) {
                let expected = cpu.sample_zone(&view, zone);
                ensure!(
                    actual.srgb == expected.srgb
                        && actual.linear_rgb == expected.linear_rgb
                        && actual.encoded_variance == expected.encoded_variance
                        && actual.pixel_count == expected.pixel_count,
                    "Texture sampling colour mismatch"
                );
                comparisons += 1;
            }
            let moved: Vec<_> = zones
                .iter()
                .map(|z| ZoneRect {
                    x: z.x + 3,
                    y: z.y + 2,
                    ..*z
                })
                .collect();
            sampler.set_zones(&moved)?;
            let (updated, _) = sampler.sample(&texture)?;
            for (actual, &zone) in updated.iter().zip(&moved) {
                let expected = cpu.sample_zone(&view, zone);
                ensure!(
                    actual.srgb == expected.srgb
                        && actual.linear_rgb == expected.linear_rgb
                        && actual.encoded_variance == expected.encoded_variance
                        && actual.pixel_count == expected.pixel_count,
                    "Updated texture zones changed colours"
                );
                updated_zone_comparisons += 1;
            }
            sampler.set_zones(&zones)?;
            results.push(serde_json::json!({"format":format!("{format:?}"),"pattern":pattern,"all_fields_exact":true,"timings":timings}));
        }
    }
    println!(
        "{}",
        serde_json::json!({"adapter":adapter,"scope":"Synthetic Vulkan texture shader and diagnostic readback oracle; DMA-BUF import not exercised by this test","zone_comparisons":comparisons,"region_comparisons":region_comparisons,"updated_zone_comparisons":updated_zone_comparisons,"cases":results})
    );
    Ok(())
}
