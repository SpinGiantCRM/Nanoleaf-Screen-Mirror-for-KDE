//! Hardware-only exact line-total and conservative-decision oracle.
use anyhow::{ensure, Result};
use nanoleaf_linux_gpu::{border::certify_luma_above, RegionReader};
use nanoleaf_native::pipeline::encoded_mean;
use nanoleaf_vulkan_probe::TextureSampler;

pub fn run(device: wgpu::Device, queue: wgpu::Queue, adapter: serde_json::Value) -> Result<()> {
    let mut sums_checked = 0;
    let mut certificates_checked = 0;
    let mut ambiguous = 0;
    let mut cached_range_checks = 0;
    let maximum = device.limits().max_texture_dimension_2d.min(16384);
    let sizes = [
        (1, 1),
        (7, 9),
        (97, 65),
        (641, 359),
        (maximum, 3),
        (3, maximum),
    ];
    for (w, h) in sizes {
        let sampler = TextureSampler::new(
            device.clone(),
            queue.clone(),
            w,
            h,
            &[nanoleaf_core::sampling::ZoneRect {
                x: 0,
                y: 0,
                width: w.into(),
                height: h.into(),
            }],
        )?;
        for format in [
            wgpu::TextureFormat::Rgba8Unorm,
            wgpu::TextureFormat::Bgra8Unorm,
        ] {
            let texture = device.create_texture(&wgpu::TextureDescriptor {
                label: Some("Generated line-statistics oracle"),
                size: wgpu::Extent3d {
                    width: w,
                    height: h,
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
            for pattern in 0..5 {
                let mut rgb = Vec::new();
                let mut bytes = Vec::new();
                for y in 0..h {
                    for x in 0..w {
                        let n = x + y * w;
                        let value = match pattern {
                            0 => [4; 3],
                            1 => [(n % 4) as u8, ((n * 7) % 4) as u8, ((n * 13) % 4) as u8],
                            2 => [(n % 9) as u8, ((n * 7) % 9) as u8, ((n * 13) % 9) as u8],
                            _ => [
                                (n % 256) as u8,
                                ((n * 43) % 256) as u8,
                                ((n * 73) % 256) as u8,
                            ],
                        };
                        let alpha = if pattern == 4 { (n % 256) as u8 } else { 255 };
                        rgb.extend_from_slice(&if alpha == 0 { [0; 3] } else { value });
                        let wire = if format == wgpu::TextureFormat::Bgra8Unorm {
                            [value[2], value[1], value[0], alpha]
                        } else {
                            [value[0], value[1], value[2], alpha]
                        };
                        bytes.extend_from_slice(&wire);
                    }
                }
                queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture: &texture,
                        mip_level: 0,
                        origin: wgpu::Origin3d::ZERO,
                        aspect: wgpu::TextureAspect::All,
                    },
                    &bytes,
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(w * 4),
                        rows_per_image: Some(h),
                    },
                    texture.size(),
                );
                let pixels = |vertical: bool, line: u32, start: u32, end: u32| -> Vec<u8> {
                    (start..end)
                        .flat_map(|i| {
                            let (x, y) = if vertical { (line, i) } else { (i, line) };
                            let at = (y * w + x) as usize * 3;
                            rgb[at..at + 3].iter().copied()
                        })
                        .collect()
                };
                for vertical in [false, true] {
                    let (limit, span) = if vertical { (w, h) } else { (h, w) };
                    for (start, end) in [(0, span), (span / 4, (span * 3 / 4).max(span / 4 + 1))] {
                        let actual = sampler.line_sums(&texture, vertical, start, end)?;
                        let positions: Vec<_> = (0..limit)
                            .step_by(8)
                            .chain((0..limit).rev().step_by(8))
                            .collect();
                        ensure!(actual.len() == positions.len(), "Line count mismatch");
                        for (&line, totals) in positions.iter().zip(actual) {
                            let data = pixels(vertical, line, start, end);
                            let mut expected = [0, 0, 0, end - start];
                            for pixel in data.chunks_exact(3) {
                                for k in 0..3 {
                                    expected[k] += u32::from(pixel[k]);
                                }
                            }
                            ensure!(totals == expected, "Integer line total mismatch");
                            sums_checked += 1;
                            match certify_luma_above(totals, 4.0) {
                                Some(value) => {
                                    ensure!(
                                        value == (encoded_mean(&data)? > 4.0),
                                        "Certificate changed threshold decision"
                                    );
                                    certificates_checked += 1;
                                }
                                None => ambiguous += 1,
                            }
                        }
                    }
                }
                // Same reader, changing/reversing ranges and returning to the old
                // range. No certificate from a previous span may be reused.
                let mut reader = RegionReader::new(&sampler, &texture);
                for (top, bottom) in [(0, h), (h / 4, (h * 3 / 4).max(h / 4 + 1)), (0, h)] {
                    for x in [8.min(w - 1), w - 1 - (8.min(w - 1))] {
                        if let Some(value) = reader.column_luma_above(x, top, bottom, 4.0)? {
                            ensure!(
                                value == (encoded_mean(&pixels(true, x, top, bottom))? > 4.0),
                                "Cached column span changed decision"
                            );
                            cached_range_checks += 1;
                        }
                    }
                }
                ensure!(
                    reader.row_luma_above(h, 4.0).is_err(),
                    "Out-of-range row accepted"
                );
                ensure!(
                    reader.column_luma_above(0, 0, 0, 4.0).is_err(),
                    "Empty column accepted"
                );
                ensure!(
                    sampler.line_sums(&texture, true, 0, h + 1).is_err(),
                    "Out-of-range span accepted"
                );
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Generated hardware Vulkan textures only; no capture, HID or saved configuration changes","adapter":adapter,"sizes":sizes,"formats":["RGBA8","BGRA8"],"patterns_per_format":5,"exact_line_totals":sums_checked,"certified_cpu_threshold_matches":certificates_checked,"ambiguous_requires_original_pixels":ambiguous,"cached_column_range_checks":cached_range_checks})
    );
    Ok(())
}
