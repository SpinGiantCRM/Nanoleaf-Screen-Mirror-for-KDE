use nanoleaf_native::{
    capture::Frame,
    config::{Config, Rect},
    pipeline::{quantize, Pipeline},
};
use serde::Deserialize;
#[derive(Deserialize)]
struct Case {
    style: String,
    quality: String,
    sampling: String,
    box_filter: bool,
    locality: String,
    anchors: [i64; 4],
    width: usize,
    height: usize,
    frames: Vec<Oracle>,
}
#[derive(Deserialize)]
struct Oracle {
    offset: usize,
    sampled: Vec<[u8; 3]>,
    colors: Vec<[u8; 3]>,
}
#[test]
fn evolving_full_pipeline_matches_reference_except_corrected_dither() {
    let cases: Vec<Case> =
        serde_json::from_str(include_str!("../../fixtures/pipeline.json")).unwrap();
    let mut maximum = 0;
    for case in cases {
        let mut c = Config {
            color_style: case.style.clone(),
            sampling_quality: case.quality.clone(),
            sampling_mode: case.sampling.clone(),
            zone_box_filter_sampling: case.box_filter,
            edge_locality: case.locality.clone(),
            device_zone_count: 48,
            blue_noise_dither: false,
            ..Default::default()
        };
        let [a, b, d, e] = case.anchors;
        c.calibration.corner_anchor_top_left = a;
        c.calibration.corner_anchor_top_right = b;
        c.calibration.corner_anchor_bottom_right = d;
        c.calibration.corner_anchor_bottom_left = e;
        if c.sampling_quality == "balanced" {
            c.privacy_zones.push(Rect {
                x: 0.15,
                y: 0.2,
                w: 0.3,
                h: 0.4,
            });
        }
        let mut p = Pipeline::default();
        for (index, oracle) in case.frames.into_iter().enumerate() {
            let frame = Frame {
                width: case.width,
                height: case.height,
                pixels: include_bytes!("../../fixtures/pipeline-rgb.bin")
                    [oracle.offset..oracle.offset + case.width * case.height * 3]
                    .to_vec(),
            };
            let out = p.process(&frame, &c).unwrap();
            for (zone, (a, e)) in out.sampled.iter().zip(&oracle.sampled).enumerate() {
                assert_eq!(
                    a, e,
                    "sampling {} {} frame {index} zone {zone}",
                    case.style, case.quality
                );
            }
            for (zone, (a, e)) in out.colors.iter().zip(&oracle.colors).enumerate() {
                for k in 0..3 {
                    let delta = a[k].abs_diff(e[k]);
                    maximum = maximum.max(delta);
                    assert!(
                        delta <= 1,
                        "output {} {} frame {index} zone {zone}: {a:?} vs {e:?}",
                        case.style,
                        case.quality
                    );
                }
            }
        }
    }
    eprintln!("maximum output code delta {maximum}");
}
#[test]
fn dither_is_bounded_neutral_and_black_remains_off() {
    for frame in 0..64 {
        for code in 0..=255 {
            let rgb = [code as f32; 3];
            let actual = quantize(rgb, true, frame, 7);
            assert_eq!(actual, [actual[0]; 3]);
            assert_eq!(actual[0], code);
            assert_eq!(quantize([0.0; 3], true, frame, 7), [0; 3]);
        }
    }
    let average = (0..8)
        .map(|f| quantize([128.25; 3], true, f, 0)[0] as f32)
        .sum::<f32>()
        / 8.0;
    assert_eq!(average, 128.25);
}

#[test]
fn steady_neutral_dither_keeps_fractional_brightness_instead_of_integer_hold() {
    use nanoleaf_core::colour::{decode_srgb, encode_srgb};
    let mut c = Config {
        device_zone_count: 4,
        color_style: "reference".into(),
        brightness: 0.5,
        blue_noise_dither: true,
        letterbox_detection: false,
        ..Default::default()
    };
    c.calibration.corner_anchor_top_left = 0;
    c.calibration.corner_anchor_top_right = 1;
    c.calibration.corner_anchor_bottom_right = 2;
    c.calibration.corner_anchor_bottom_left = 3;
    let frame = Frame {
        width: 32,
        height: 24,
        pixels: vec![128; 32 * 24 * 3],
    };
    let mut p = Pipeline::default();
    let mut sum = 0.0;
    for _ in 0..8 {
        let out = p.process(&frame, &c).unwrap();
        assert_eq!(out.colors[0], [out.colors[0][0]; 3]);
        sum += out.colors[0][0] as f32;
    }
    let target = encode_srgb(decode_srgb(128.0) * 0.5);
    assert!((sum / 8.0 - target).abs() < 0.07, "{sum} vs {target}");
}

#[test]
fn external_sdr_statistics_preserve_the_full_colour_and_ack_history_pipeline() {
    use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler};
    use nanoleaf_native::pipeline::direct_plan;
    for style in ["reference", "ambient", "vivid"] {
        for dither in [false, true] {
            let mut c = Config {
                device_zone_count: 48,
                color_style: style.into(),
                sampling_mode: "area_average".into(),
                letterbox_detection: false,
                blue_noise_dither: dither,
                zone_temporal_accumulation: true,
                brightness: 0.73,
                ..Default::default()
            };
            c.calibration.corner_anchor_top_left = 0;
            c.calibration.corner_anchor_top_right = 12;
            c.calibration.corner_anchor_bottom_right = 24;
            c.calibration.corner_anchor_bottom_left = 36;
            c.led_calibration_profile_sdr.red_gain = 0.873123456789;
            c.led_calibration_profile_sdr.color_matrix =
                vec![1.0, 0.02, 0.0, 0.01, 0.98, 0.01, 0.0, 0.02, 1.0];
            let (mut cpu, mut external) = (Pipeline::default(), Pipeline::default());
            let sampler = SdrSampler::default();
            for index in 0..40 {
                let mut frame = Frame {
                    width: 96,
                    height: 64,
                    pixels: Vec::new(),
                };
                for pixel in 0..96 * 64 {
                    let rgb = match index % 8 {
                        0 => [0; 3],
                        1 => [255; 3],
                        2 => [128; 3],
                        3 => [9; 3],
                        _ => [
                            ((pixel + index * 11) % 256) as u8,
                            ((pixel * 17 + index * 19) % 256) as u8,
                            ((pixel * 43 + index * 7) % 256) as u8,
                        ],
                    };
                    frame.pixels.extend_from_slice(&rgb);
                }
                let plan = direct_plan(&c, 96, 64).unwrap();
                let view = SdrRgb8Frame::new(&frame.pixels, 96, 64, 96 * 3).unwrap();
                let samples: Vec<_> = plan
                    .zones
                    .iter()
                    .map(|&z| sampler.sample_zone(&view, z))
                    .collect();
                let expected = cpu.process(&frame, &c).unwrap();
                let actual = external.process_sdr_samples(96, 64, &samples, &c).unwrap();
                assert_eq!(
                    actual.sampled, expected.sampled,
                    "{style} {dither} frame {index}"
                );
                assert_eq!(
                    actual.colors, expected.colors,
                    "{style} {dither} frame {index}"
                );
                assert_eq!(actual.modes, expected.modes);
                // The USB actor can skip a queued frame. Both paths must use the
                // colours actually acknowledged, including an unrelated preview.
                let ack = if index % 9 == 0 {
                    vec![[60, 20, 30]; 48]
                } else {
                    expected.colors
                };
                cpu.override_sent(&ack);
                external.override_sent(&ack);
            }
        }
    }
}
#[test]
fn direct_sampling_cannot_silently_disable_pixel_dependent_policies() {
    use nanoleaf_native::pipeline::direct_plan;
    let mut c = Config {
        device_zone_count: 4,
        color_style: "reference".into(),
        letterbox_detection: false,
        ..Default::default()
    };
    c.calibration.corner_anchor_top_left = 0;
    c.calibration.corner_anchor_top_right = 1;
    c.calibration.corner_anchor_bottom_right = 2;
    c.calibration.corner_anchor_bottom_left = 3;
    assert!(direct_plan(&c, 32, 24).is_ok());
    c.letterbox_detection = true;
    assert!(direct_plan(&c, 32, 24).is_err());
    c.letterbox_detection = false;
    c.privacy_zones.push(Rect {
        x: 0.1,
        y: 0.1,
        w: 0.2,
        h: 0.2,
    });
    assert!(direct_plan(&c, 32, 24).is_err());
    c.privacy_zones.clear();
    c.zone_box_filter_sampling = false;
    assert!(direct_plan(&c, 32, 24).is_err());
    c.zone_box_filter_sampling = true;
    c.color_style = "ambient".into();
    c.sampling_mode = "palette_adaptive".into();
    assert!(direct_plan(&c, 32, 24).is_err());
}

#[test]
fn exact_sparse_letterbox_analysis_matches_full_pixel_processing() {
    use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler};
    use nanoleaf_native::pipeline::{detect_content_bounds, direct_plan_with_bounds, encoded_mean};
    let mut c = Config {
        device_zone_count: 48,
        color_style: "reference".into(),
        letterbox_detection: true,
        ..Default::default()
    };
    c.calibration.corner_anchor_top_left = 0;
    c.calibration.corner_anchor_top_right = 12;
    c.calibration.corner_anchor_bottom_right = 24;
    c.calibration.corner_anchor_bottom_left = 36;
    let (mut full, mut sparse) = (Pipeline::default(), Pipeline::default());
    let sampler = SdrSampler::default();
    for bars in [(0, 0), (16, 0), (0, 24), (16, 24), (32, 40)] {
        for level in [0, 4, 5, 20, 128, 255] {
            let (w, h) = (160, 96);
            let mut pixels = vec![0_u8; w * h * 3];
            for y in bars.0..h - bars.0 {
                for x in bars.1..w - bars.1 {
                    pixels[(y * w + x) * 3..(y * w + x) * 3 + 3].copy_from_slice(&[level; 3]);
                }
            }
            let bounds = detect_content_bounds(
                w,
                h,
                |y| encoded_mean(&pixels[y * w * 3..(y + 1) * w * 3]),
                |x, top, bottom| {
                    let data: Vec<_> = (top..bottom)
                        .flat_map(|y| pixels[(y * w + x) * 3..(y * w + x) * 3 + 3].iter().copied())
                        .collect();
                    encoded_mean(&data)
                },
            )
            .unwrap();
            let plan = direct_plan_with_bounds(&c, w, h, Some(bounds)).unwrap();
            let view = SdrRgb8Frame::new(&pixels, w, h, w * 3).unwrap();
            let samples: Vec<_> = plan
                .zones
                .iter()
                .map(|&z| sampler.sample_zone(&view, z))
                .collect();
            let expected = full
                .process(
                    &Frame {
                        width: w,
                        height: h,
                        pixels,
                    },
                    &c,
                )
                .unwrap();
            let actual = sparse
                .process_sdr_samples_with_bounds(w, h, &samples, &c, Some(bounds))
                .unwrap();
            assert_eq!(actual.sampled, expected.sampled, "{bars:?} {level}");
            assert_eq!(actual.colors, expected.colors, "{bars:?} {level}");
        }
    }
}
