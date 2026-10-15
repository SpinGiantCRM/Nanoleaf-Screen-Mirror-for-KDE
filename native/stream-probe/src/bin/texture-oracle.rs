//! Hardware texture shader oracle. No capture permission, HID or saved frames.
#[path = "../gpu.rs"]
mod gpu;
use anyhow::{ensure, Result};
use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect};
use nanoleaf_vulkan_probe::TextureSampler;
fn main() -> Result<()> {
    let (device, queue, adapter) = gpu::prepare()?;
    if std::env::args().nth(1).as_deref() == Some("--edge-benchmark") {
        return edge_benchmark(device, queue, adapter);
    }
    if std::env::args().nth(1).as_deref() == Some("--sampling-benchmark") {
        return sampling_benchmark(device, queue, adapter);
    }
    if std::env::args().nth(1).as_deref() == Some("--content-benchmark") {
        return content_benchmark(device, queue, adapter);
    }
    if std::env::args().nth(1).as_deref() == Some("--uniform-oracle") {
        return uniform_oracle(device, queue, adapter);
    }
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
    let mut reader_comparisons = 0;
    let mut region_comparisons = 0;
    let mut updated_zone_comparisons = 0;
    let mut batch_comparisons = 0;
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
        for pattern in [
            "black",
            "grey",
            "white",
            "all_codes",
            "mixed",
            "transparent",
        ] {
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
                let alpha = if pattern == "transparent" && n % 7 == 0 {
                    0
                } else {
                    255
                };
                rgb.extend_from_slice(&if alpha == 0 { [0; 3] } else { value });
                if format == wgpu::TextureFormat::Bgra8Unorm {
                    encoded.extend_from_slice(&[value[2], value[1], value[0], alpha]);
                } else {
                    encoded.extend_from_slice(&[value[0], value[1], value[2], alpha]);
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
            let rects = [
                [0, 0, 96, 1],
                [0, 63, 96, 1],
                [23, 7, 1, 41],
                [17, 13, 29, 19],
            ];
            let batch = sampler.regions_rgb(&texture, &rects)?;
            for (rect, batched) in rects.into_iter().zip(batch) {
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
                ensure!(
                    batched == expected,
                    "Batched region extraction changed encoded pixels"
                );
                batch_comparisons += 1;
                region_comparisons += 1;
            }
            let mut reader = nanoleaf_linux_gpu::RegionReader::new(&sampler, &texture);
            for y in [0u32, 8, 16, 63, 4, 12, 4] {
                ensure!(
                    reader.row(y)? == rgb[y as usize * 96 * 3..(y as usize + 1) * 96 * 3],
                    "Prefetched row changed exact encoded pixels"
                );
                reader_comparisons += 1;
            }
            for (x, top, bottom) in [
                (8u32, 0u32, 64u32),
                (16, 7, 49),
                (8, 0, 64),
                (20, 5, 55),
                (95, 0, 64),
            ] {
                let expected: Vec<_> = (top..bottom)
                    .flat_map(|y| {
                        let i = (y as usize * 96 + x as usize) * 3;
                        rgb[i..i + 3].iter().copied()
                    })
                    .collect();
                ensure!(
                    reader.column(x, top, bottom)? == expected,
                    "Prefetched column/range changed exact encoded pixels"
                );
                reader_comparisons += 1;
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
        serde_json::json!({"adapter":adapter,"scope":"Synthetic Vulkan texture shader and diagnostic readback oracle; DMA-BUF import not exercised by this test","zone_comparisons":comparisons,"reader_comparisons":reader_comparisons,"region_comparisons":region_comparisons,"batch_region_comparisons":batch_comparisons,"updated_zone_comparisons":updated_zone_comparisons,"cases":results})
    );
    Ok(())
}

fn edge_benchmark(
    device: wgpu::Device,
    queue: wgpu::Queue,
    adapter: serde_json::Value,
) -> Result<()> {
    use std::time::Instant;
    let (w, h) = (3840, 2160);
    let sampler = TextureSampler::new(
        device,
        queue,
        w,
        h,
        &[ZoneRect {
            x: 0,
            y: 0,
            width: 3840,
            height: 2160,
        }],
    )?;
    let texture = sampler.device().create_texture(&wgpu::TextureDescriptor {
        label: Some("Synthetic 4K edge batch benchmark"),
        size: wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Bgra8Unorm,
        usage: wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::COPY_DST
            | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let pixels: Vec<_> = (0..w * h)
        .flat_map(|n| {
            [
                (n % 256) as u8,
                ((n * 7) % 256) as u8,
                ((n * 13) % 256) as u8,
                255,
            ]
        })
        .collect();
    sampler.queue().write_texture(
        wgpu::TexelCopyTextureInfo {
            texture: &texture,
            mip_level: 0,
            origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::All,
        },
        &pixels,
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(w * 4),
            rows_per_image: Some(h),
        },
        texture.size(),
    );
    let rects = [
        [0, 0, w, 1],
        [0, h - 1, w, 1],
        [0, 0, 1, h],
        [w - 1, 0, 1, h],
    ];
    let reference: Vec<_> = rects
        .iter()
        .map(|&r| sampler.region_rgb(&texture, r))
        .collect::<Result<_>>()?;
    for _ in 0..10 {
        ensure!(
            sampler.regions_rgb(&texture, &rects)? == reference,
            "Warm batch parity failed"
        );
    }
    let mut sequential = Vec::new();
    let mut batched = Vec::new();
    for trial in 0..100 {
        for batch in if trial % 2 == 0 {
            [false, true]
        } else {
            [true, false]
        } {
            let started = Instant::now();
            let actual = if batch {
                sampler.regions_rgb(&texture, &rects)?
            } else {
                rects
                    .iter()
                    .map(|&r| sampler.region_rgb(&texture, r))
                    .collect::<Result<_>>()?
            };
            let ms = started.elapsed().as_secs_f64() * 1000.0;
            ensure!(actual == reference, "Edge benchmark changed pixels");
            if batch {
                batched.push(ms);
            } else {
                sequential.push(ms);
            }
        }
    }
    fn metrics(mut values: Vec<f64>) -> serde_json::Value {
        let raw = values.clone();
        values.sort_by(f64::total_cmp);
        serde_json::json!({"samples_ms":raw,"median_ms":(values[49]+values[50])/2.0,"p95_ms":values[94]})
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Synthetic 4K exact edge readback only; no DMA-BUF/capture/USB/optical/power claim",
        "adapter":adapter,"size":[w,h],"alternating_order":true,"trials":100,"all_pixels_exact":true,
        "sequential":metrics(sequential),"batched":metrics(batched),"rgb_bytes":reference.iter().map(Vec::len).sum::<usize>()})
    );
    Ok(())
}

/// Production texture sampler under reproducible colour distributions. Upload,
/// allocation, CPU oracle and warm-up are outside the timed sample window.
fn sampling_benchmark(
    device: wgpu::Device,
    queue: wgpu::Queue,
    adapter: serde_json::Value,
) -> Result<()> {
    let (width, height) = (3840u32, 2160u32);
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("Generated 4K sampling benchmark"),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    let mut cases = Vec::new();
    let mut comparisons = 0;
    for layout in ["edges", "full-stripes"] {
        let mut zones = Vec::new();
        for i in 0..12u32 {
            for z in [
                ZoneRect {
                    x: (i * width / 12) as i64,
                    y: 0,
                    width: (width / 12) as i64,
                    height: (height / 14) as i64,
                },
                ZoneRect {
                    x: (i * width / 12) as i64,
                    y: (height - height / 14) as i64,
                    width: (width / 12) as i64,
                    height: (height / 14) as i64,
                },
                ZoneRect {
                    x: 0,
                    y: (i * height / 12) as i64,
                    width: (width / 14) as i64,
                    height: (height / 12) as i64,
                },
                ZoneRect {
                    x: (width - width / 14) as i64,
                    y: (i * height / 12) as i64,
                    width: (width / 14) as i64,
                    height: (height / 12) as i64,
                },
            ] {
                zones.push(z);
            }
        }
        if layout == "full-stripes" {
            for (i, z) in zones.iter_mut().enumerate() {
                *z = ZoneRect {
                    x: i as i64 * 80,
                    y: 0,
                    width: 80,
                    height: height as i64,
                };
            }
        }
        let sampler = TextureSampler::new(device.clone(), queue.clone(), width, height, &zones)?;
        for pattern in ["grey", "split", "noise"] {
            let mut rgb = Vec::with_capacity(width as usize * height as usize * 3);
            let mut encoded = Vec::with_capacity(width as usize * height as usize * 4);
            for n in 0..width * height {
                let value = match pattern {
                    "grey" => [128, 128, 128],
                    "split" => {
                        if n % width < width / 2 {
                            [25, 170, 45]
                        } else {
                            [210, 20, 25]
                        }
                    }
                    _ => [
                        (n.wrapping_mul(1664525).wrapping_add(1013904223) >> 24) as u8,
                        (n.wrapping_mul(22695477).wrapping_add(1) >> 24) as u8,
                        (n.wrapping_mul(1103515245).wrapping_add(12345) >> 24) as u8,
                    ],
                };
                rgb.extend_from_slice(&value);
                encoded.extend_from_slice(&[value[0], value[1], value[2], 255]);
            }
            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                &encoded,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(width * 4),
                    rows_per_image: Some(height),
                },
                texture.size(),
            );
            let view =
                SdrRgb8Frame::new(&rgb, width as usize, height as usize, width as usize * 3)?;
            let cpu = SdrSampler::default();
            let reference: Vec<_> = zones.iter().map(|&z| cpu.sample_zone(&view, z)).collect();
            for _ in 0..2 {
                sampler.sample(&texture)?;
            }
            let mut timings = Vec::new();
            for _ in 0..7 {
                let (sampled, timing) = sampler.sample(&texture)?;
                for (a, b) in sampled.iter().zip(&reference) {
                    ensure!(
                        a.srgb == b.srgb
                            && a.linear_rgb == b.linear_rgb
                            && a.encoded_variance == b.encoded_variance
                            && a.pixel_count == b.pixel_count,
                        "4K texture sampling lost exact colour parity"
                    );
                    comparisons += 1;
                }
                timings.push(timing);
            }
            cases.push(serde_json::json!({"layout":layout,"pattern":pattern,"timings":timings,"all_fields_exact":true}));
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Generated 4K texture sampling only; no capture/USB/optical measurement; excludes upload, startup and CPU oracle; two warm-ups and seven timed samples per case","adapter":adapter,"zone_comparisons":comparisons,"cases":cases})
    );
    Ok(())
}

fn content_benchmark(
    device: wgpu::Device,
    queue: wgpu::Queue,
    adapter: serde_json::Value,
) -> Result<()> {
    use nanoleaf_linux_gpu::RegionReader;
    use nanoleaf_native::pipeline::{detect_content_bounds, encoded_mean};
    use std::{cell::RefCell, time::Instant};
    let calibration = if std::env::args().nth(2).as_deref() == Some("--calibration") {
        let path = std::env::args()
            .nth(3)
            .ok_or_else(|| anyhow::anyhow!("Existing calibration config required"))?;
        Some(nanoleaf_native::config::Store::load(std::path::Path::new(&path))?.config)
    } else {
        None
    };
    let mut cases = Vec::new();
    for (w, h) in [(641u32, 359u32), (3840, 2160)] {
        let sampler = TextureSampler::new(
            device.clone(),
            queue.clone(),
            w,
            h,
            &[ZoneRect {
                x: 0,
                y: 0,
                width: w as i64,
                height: h as i64,
            }],
        )?;
        let mut calibrated_sampler = if let Some(config) = &calibration {
            let full = nanoleaf_native::pipeline::ContentBounds {
                left: 0,
                top: 0,
                right: w as usize,
                bottom: h as usize,
            };
            let zones = nanoleaf_native::pipeline::direct_plan_with_bounds(
                config,
                w as usize,
                h as usize,
                Some(full),
            )?
            .zones;
            Some(TextureSampler::new(
                device.clone(),
                queue.clone(),
                w,
                h,
                &zones,
            )?)
        } else {
            None
        };
        let mut reference_pipeline = nanoleaf_native::pipeline::Pipeline::default();
        let mut calibrated_pipeline = nanoleaf_native::pipeline::Pipeline::default();
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("Generated content detector oracle"),
            size: wgpu::Extent3d {
                width: w,
                height: h,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_DST
                | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        for pattern in [
            "bright",
            "thin-bars",
            "cinema-bars",
            "pillars",
            "black",
            "dark-grey",
            "threshold-grey",
            "single-pixel",
            "near-threshold",
            "transparent-border",
        ] {
            let mut rgb = Vec::new();
            let mut encoded = Vec::new();
            for y in 0..h {
                for x in 0..w {
                    let dark = match pattern {
                        "black" | "dark-grey" | "threshold-grey" | "single-pixel" => true,
                        "thin-bars" => y < 32 || y >= h - 32,
                        "cinema-bars" => y < h / 8 || y >= h - h / 8,
                        "pillars" => x < w / 7 || x >= w - w / 7,
                        "near-threshold" => y < 32 || y >= h - 32,
                        "transparent-border" => y < 32 || y >= h - 32,
                        _ => false,
                    };
                    let value = if pattern == "dark-grey" {
                        [1; 3]
                    } else if pattern == "threshold-grey" {
                        [4; 3]
                    } else if pattern == "single-pixel" && x == w / 2 && y == h / 2 {
                        [255; 3]
                    } else if pattern == "near-threshold" {
                        if dark {
                            [4, 4, 4]
                        } else {
                            [5, 4, 4]
                        }
                    } else if dark {
                        [0, 0, 0]
                    } else {
                        [127, 130, 125]
                    };
                    let alpha = if pattern == "transparent-border" && dark {
                        0
                    } else {
                        255
                    };
                    let raw = if alpha == 0 { [230, 14, 198] } else { value };
                    rgb.extend_from_slice(&value);
                    encoded.extend_from_slice(&[raw[0], raw[1], raw[2], alpha]);
                }
            }
            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                &encoded,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(w * 4),
                    rows_per_image: Some(h),
                },
                texture.size(),
            );
            let reference = detect_content_bounds(
                w as usize,
                h as usize,
                |y| encoded_mean(&rgb[y * w as usize * 3..(y + 1) * w as usize * 3]),
                |x, top, bottom| {
                    let column: Vec<_> = (top..bottom)
                        .flat_map(|y| {
                            let i = (y * w as usize + x) * 3;
                            rgb[i..i + 3].iter().copied()
                        })
                        .collect();
                    encoded_mean(&column)
                },
            )?;
            let mut runs = Vec::new();
            let mut last_bounds = reference;
            for run in 0..7 {
                let reader = RefCell::new(RegionReader::new(&sampler, &texture));
                let started = Instant::now();
                let actual = if std::env::args().nth(2).as_deref() != Some("--reference")
                    && reader.borrow_mut().uniform_dark()?
                {
                    nanoleaf_native::pipeline::ContentBounds {
                        left: 0,
                        top: 0,
                        right: w as usize,
                        bottom: h as usize,
                    }
                } else {
                    detect_content_bounds(
                        w as usize,
                        h as usize,
                        |y| encoded_mean(&reader.borrow_mut().row(y as u32)?),
                        |x, top, bottom| {
                            encoded_mean(&reader.borrow_mut().column(
                                x as u32,
                                top as u32,
                                bottom as u32,
                            )?)
                        },
                    )?
                };
                last_bounds = actual;
                let ms = started.elapsed().as_secs_f64() * 1000.0;
                ensure!(
                    actual == reference,
                    "GPU content detection changed exact ordered-CPU bounds"
                );
                if run >= 2 {
                    let (bytes, batches) = reader.borrow().statistics();
                    runs.push(
                        serde_json::json!({"ms":ms,"rgb_bytes":bytes,"transfer_batches":batches}),
                    );
                }
            }
            let calibrated_exact =
                if let (Some(config), Some(sampler)) = (&calibration, &mut calibrated_sampler) {
                    use nanoleaf_native::{capture::Frame, pipeline::direct_plan_with_bounds};
                    let bounds = config.letterbox_detection.then_some(last_bounds);
                    sampler.set_zones(
                        &direct_plan_with_bounds(config, w as usize, h as usize, bounds)?.zones,
                    )?;
                    let (samples, _) = sampler.sample(&texture)?;
                    let frame = Frame {
                        width: w as usize,
                        height: h as usize,
                        pixels: rgb,
                    };
                    let elapsed = std::time::Duration::from_secs_f64(1.0 / config.fps as f64);
                    reference_pipeline.set_temporal_elapsed(elapsed);
                    calibrated_pipeline.set_temporal_elapsed(elapsed);
                    let reference = reference_pipeline.process(&frame, config)?;
                    let actual = calibrated_pipeline.process_sdr_samples_with_bounds(
                        w as usize, h as usize, &samples, config, bounds,
                    )?;
                    ensure!(
                        actual.colors == reference.colors
                            && actual.sampled == reference.sampled
                            && actual.modes == reference.modes
                            && actual.unquantized_rgb == reference.unquantized_rgb,
                        "Complete calibrated dark transition lost exact colour parity"
                    );
                    reference_pipeline.override_sent(&reference.colors);
                    calibrated_pipeline.override_sent(&actual.colors);
                    Some(true)
                } else {
                    None
                };
            cases.push(serde_json::json!({"width":w,"height":h,"pattern":pattern,"all_bounds_exact":true,"calibrated_full_output_exact":calibrated_exact,"runs":runs}));
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Generated RGBA texture and actual content detector/RegionReader; CPU ordered float32 oracle; no capture, USB or saved frames; upload/startup/two warm-ups excluded","adapter":adapter,"cases":cases})
    );
    Ok(())
}

fn uniform_oracle(
    device: wgpu::Device,
    queue: wgpu::Queue,
    adapter: serde_json::Value,
) -> Result<()> {
    let mut comparisons = 0;
    let mut reader_checks = 0;
    for (w, h) in [(1u32, 1u32), (257, 129), (3840, 2160)] {
        let sampler = TextureSampler::new(
            device.clone(),
            queue.clone(),
            w,
            h,
            &[ZoneRect {
                x: 0,
                y: 0,
                width: 1,
                height: 1,
            }],
        )?;
        for format in [
            wgpu::TextureFormat::Rgba8Unorm,
            wgpu::TextureFormat::Bgra8Unorm,
        ] {
            let texture = device.create_texture(&wgpu::TextureDescriptor {
                label: Some("Generated uniformity oracle"),
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
                    | wgpu::TextureUsages::COPY_SRC
                    | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            });
            let count = (w * h) as usize;
            let mut cases: Vec<(u8, Option<usize>, bool)> = if w == 257 {
                (0..=255).map(|code| (code, None, false)).collect()
            } else {
                vec![
                    (0, None, false),
                    (1, None, false),
                    (4, None, false),
                    (255, None, false),
                ]
            };
            cases.push((0, None, true)); // Hidden nonuniform RGB under alpha zero.
            if count > 1 {
                for position in [0, 1, 255, 256, count / 2, count - 2, count - 1] {
                    cases.push((0, Some(position), false));
                }
                for n in 0..32 {
                    cases.push((0, Some(n * (count - 1) / 31), false));
                }
            }
            for (code, changed, transparent) in cases {
                let mut pixels = Vec::with_capacity(count * 4);
                for i in 0..count {
                    let value = if transparent {
                        [
                            (i % 256) as u8,
                            ((i * 43) % 256) as u8,
                            ((i * 73) % 256) as u8,
                            0,
                        ]
                    } else if Some(i) == changed {
                        [code.wrapping_add(1), code, code, 1]
                    } else {
                        [code, code, code, 255]
                    };
                    if format == wgpu::TextureFormat::Bgra8Unorm {
                        pixels.extend_from_slice(&[value[2], value[1], value[0], value[3]]);
                    } else {
                        pixels.extend_from_slice(&value);
                    }
                }
                queue.write_texture(
                    wgpu::TexelCopyTextureInfo {
                        texture: &texture,
                        mip_level: 0,
                        origin: wgpu::Origin3d::ZERO,
                        aspect: wgpu::TextureAspect::All,
                    },
                    &pixels,
                    wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(w * 4),
                        rows_per_image: Some(h),
                    },
                    texture.size(),
                );
                let uniform = changed.is_none();
                ensure!(
                    sampler.is_uniform(&texture)? == uniform,
                    "Uniformity proof lost one RGB code or alpha-zero normalization"
                );
                comparisons += 1;
                let mut reader = nanoleaf_linux_gpu::RegionReader::new(&sampler, &texture);
                ensure!(
                    reader.uniform_dark()? == (uniform && (transparent || code <= 4)),
                    "Dark candidate filter changed uniform proof"
                );
                reader_checks += 1;
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Generated exact normalized RGB8 oracle, no capture or USB","adapter":adapter,"uniformity_comparisons":comparisons,"reader_comparisons":reader_checks,"all_exact":true})
    );
    Ok(())
}
