//! Bounded synthetic Vulkan-vs-CPU oracle and complete transfer benchmark.
use anyhow::Result;
use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect};
use nanoleaf_vulkan_probe::VulkanSampler;
use std::{hint::black_box, time::Instant};
fn main() -> Result<()> {
    let quick = std::env::args().any(|a| a == "--quick");
    let sizes = if quick {
        vec![(96, 64)]
    } else {
        vec![(640, 360), (2560, 1440), (3840, 2160)]
    };
    let mut results = Vec::new();
    let mut adapter = serde_json::Value::Null;
    let mut startup_ms = Vec::new();
    for (width, height) in sizes {
        let stride = width * 3 + 7;
        let mut zones = Vec::new();
        for i in 0..12 {
            let w = width / 12;
            let h = height / 12;
            for z in [
                ZoneRect {
                    x: (i * w) as i64,
                    y: 0,
                    width: w as i64,
                    height: (height / 14) as i64,
                },
                ZoneRect {
                    x: 0,
                    y: (i * h) as i64,
                    width: (width / 14) as i64,
                    height: h as i64,
                },
                ZoneRect {
                    x: (i * w) as i64,
                    y: (height - height / 14) as i64,
                    width: w as i64,
                    height: (height / 14) as i64,
                },
                ZoneRect {
                    x: (width - width / 14) as i64,
                    y: (i * h) as i64,
                    width: (width / 14) as i64,
                    height: h as i64,
                },
            ] {
                zones.push(z);
            }
        }
        let init = Instant::now();
        zones[45] = ZoneRect {
            x: -2,
            y: -3,
            width: 7,
            height: 5,
        };
        zones[46] = ZoneRect {
            x: width as i64 - 2,
            y: height as i64 - 2,
            width: 10,
            height: 10,
        };
        zones[47] = ZoneRect {
            x: width as i64 + 10,
            y: height as i64 + 10,
            width: 7,
            height: 4,
        };
        let gpu = VulkanSampler::new(width, height, stride, &zones)?;
        startup_ms.push(init.elapsed().as_secs_f64() * 1000.0);
        adapter = serde_json::json!({"name":gpu.adapter.name,"backend":format!("{:?}",gpu.adapter.backend),"device_type":format!("{:?}",gpu.adapter.device_type),"driver":gpu.adapter.driver,"driver_info":gpu.adapter.driver_info});
        for pattern in ["black", "grey", "white", "mixed", "noise"] {
            let mut data = vec![173_u8; stride * height];
            for y in 0..height {
                for x in 0..width {
                    let rgb = match pattern {
                        "black" => [0; 3],
                        "grey" => [128; 3],
                        "white" => [255; 3],
                        "mixed" => {
                            if x < width / 2 {
                                [25, 170, 45]
                            } else {
                                [210, 20, 25]
                            }
                        }
                        _ => {
                            let n = (y * width + x) as u32;
                            [
                                (n.wrapping_mul(1664525).wrapping_add(1013904223) >> 24) as u8,
                                (n.wrapping_mul(22695477).wrapping_add(1) >> 24) as u8,
                                (n.wrapping_mul(1103515245).wrapping_add(12345) >> 24) as u8,
                            ]
                        }
                    };
                    data[y * stride + x * 3..y * stride + x * 3 + 3].copy_from_slice(&rgb);
                }
            }
            let view = SdrRgb8Frame::new(&data, width, height, stride)?;
            let cpu = SdrSampler::default();
            for _ in 0..2 {
                black_box(gpu.sample(&data)?);
            }
            let mut runs = Vec::new();
            for repeat in 0..5 {
                let mut gpu_result = None;
                let mut cpu_result = None;
                for native_gpu in if repeat % 2 == 0 {
                    [true, false]
                } else {
                    [false, true]
                } {
                    if native_gpu {
                        gpu_result = Some(gpu.sample(black_box(&data))?);
                    } else {
                        let start = Instant::now();
                        let sampled: Vec<_> = zones
                            .iter()
                            .map(|&z| cpu.sample_zone(black_box(&view), z))
                            .collect();
                        cpu_result = Some((sampled, start.elapsed().as_secs_f64() * 1000.0));
                    }
                }
                let (sampled, times) = gpu_result.unwrap();
                let (reference, cpu_ms) = cpu_result.unwrap();
                for (i, (actual, expected)) in sampled.iter().zip(&reference).enumerate() {
                    assert_eq!(actual.srgb, expected.srgb, "{width} {pattern} zone {i}");
                    assert_eq!(actual.linear_rgb, expected.linear_rgb);
                    assert_eq!(actual.pixel_count, expected.pixel_count);
                    assert_eq!(actual.encoded_variance, expected.encoded_variance);
                }
                runs.push(serde_json::json!({"cpu_sampling_ms":cpu_ms,"vulkan":times,"all_fields_exact":true}));
            }
            results.push(serde_json::json!({"width":width,"height":height,"stride":stride,"zones":zones.len(),"pattern":pattern,"runs":runs}));
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Real Vulkan integer histogram dispatch, full CPU RGB upload + small histogram readback + identical CPU colour reduction. Synthetic SDR only; no capture/USB/DMA-BUF/HDR/power measurement.","adapter":adapter,"startup_ms":startup_ms,"cases":results})
    );
    Ok(())
}
