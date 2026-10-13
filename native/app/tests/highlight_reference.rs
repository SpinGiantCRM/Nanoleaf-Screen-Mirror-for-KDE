use nanoleaf_core::sampling::SdrSampler;
use serde::Deserialize;
#[derive(Deserialize)]
struct Case {
    mode: String,
    pixels: Vec<[u8; 3]>,
    rgb: [u8; 3],
    effective: String,
}
#[test]
fn highlight_policies_match_reference_and_keep_dark_mixed_guards() {
    let cases: Vec<Case> =
        serde_json::from_str(include_str!("../../fixtures/highlight-policies.json")).unwrap();
    let sampler = SdrSampler::default();
    for (index, case) in cases.iter().enumerate() {
        let (rgb, guarded) = sampler
            .highlight_mean(&case.pixels, case.mode == "peak_luma")
            .unwrap();
        assert_eq!(
            if guarded { "area_average" } else { &case.mode },
            case.effective,
            "case {index}"
        );
        for (actual, reference) in rgb.into_iter().zip(case.rgb) {
            assert!(
                actual.abs_diff(reference) <= 1,
                "case {index}: {rgb:?} vs {:?}",
                case.rgb
            );
        }
    }
}
#[test]
fn every_uniform_code_stays_exact_and_mixed_neutrals_remain_neutral() {
    let sampler = SdrSampler::default();
    for peak in [false, true] {
        assert_eq!(sampler.highlight_mean(&[], peak).unwrap().0, [0; 3]);
        for code in 0..=255 {
            assert_eq!(
                sampler
                    .highlight_mean(&vec![[code; 3]; 513], peak)
                    .unwrap()
                    .0,
                [code; 3]
            );
        }
        let pixels: Vec<_> = (0..=255).map(|v| [v; 3]).collect();
        let (rgb, _) = sampler.highlight_mean(&pixels, peak).unwrap();
        assert_eq!(rgb[0], rgb[1]);
        assert_eq!(rgb[1], rgb[2]);
    }
}

#[test]
fn highlight_modes_keep_global_letterbox_and_dark_scene_fallbacks() {
    use nanoleaf_native::{
        capture::Frame,
        config::Config,
        pipeline::{direct_plan, Pipeline},
    };
    for mode in ["peak_luma", "vivid_weighted"] {
        let mut c = Config {
            device_zone_count: 48,
            color_style: "ambient".into(),
            sampling_mode: mode.into(),
            sampling_quality: "high".into(),
            ..Default::default()
        };
        c.calibration.corner_anchor_top_left = 0;
        c.calibration.corner_anchor_top_right = 12;
        c.calibration.corner_anchor_bottom_right = 24;
        c.calibration.corner_anchor_bottom_left = 36;
        assert!(direct_plan(&c, 160, 96).is_err());
        let mut pixels = vec![0; 160 * 96 * 3];
        for y in 16..80 {
            for x in 0..160 {
                pixels[(y * 160 + x) * 3..(y * 160 + x) * 3 + 3].copy_from_slice(&[30, 160, 55]);
            }
        }
        let out = Pipeline::default()
            .process(
                &Frame {
                    width: 160,
                    height: 96,
                    pixels,
                },
                &c,
            )
            .unwrap();
        assert!(out.modes.iter().all(|m| m == "area_average"));
        let mut pipeline = Pipeline::default();
        let black = Frame {
            width: 160,
            height: 96,
            pixels: vec![0; 160 * 96 * 3],
        };
        pipeline.process(&black, &c).unwrap();
        let bright = Frame {
            width: 160,
            height: 96,
            pixels: vec![128; 160 * 96 * 3],
        };
        let out = pipeline.process(&bright, &c).unwrap();
        assert!(out.modes.iter().all(|m| m == "area_average"));
    }
}

#[test]
fn exact_patch_cache_matches_uncached_output_across_repeats_cuts_and_masks() {
    use nanoleaf_native::{
        capture::Frame,
        config::{Config, Rect},
        pipeline::Pipeline,
    };
    for mode in ["peak_luma", "vivid_weighted"] {
        let mut c = Config {
            device_zone_count: 48,
            color_style: "ambient".into(),
            sampling_mode: mode.into(),
            sampling_quality: "high".into(),
            letterbox_detection: false,
            ..Default::default()
        };
        c.calibration.corner_anchor_top_left = 0;
        c.calibration.corner_anchor_top_right = 12;
        c.calibration.corner_anchor_bottom_right = 24;
        c.calibration.corner_anchor_bottom_left = 36;
        let (mut cached, mut reference) =
            (Pipeline::default(), Pipeline::without_highlight_cache());
        let mut maximum_hits = 0;
        for index in 0..24 {
            c.privacy_zones = if index >= 12 {
                vec![Rect {
                    x: 0.0,
                    y: 0.0,
                    w: 0.15,
                    h: 1.0,
                }]
            } else {
                Vec::new()
            };
            let pixels = (0..160 * 96)
                .flat_map(|n| {
                    let period = index / 4;
                    [
                        ((n * 17 + period * 67) % 128 + 100) as u8,
                        ((n * 13 + period * 31) % 128 + 100) as u8,
                        ((n * 7 + period * 19) % 128 + 100) as u8,
                    ]
                })
                .collect();
            let frame = Frame {
                width: 160,
                height: 96,
                pixels,
            };
            let a = cached.process(&frame, &c).unwrap();
            let b = reference.process(&frame, &c).unwrap();
            assert_eq!(a.sampled, b.sampled);
            assert_eq!(a.colors, b.colors);
            assert_eq!(a.modes, b.modes);
            let (bytes, hits) = cached.highlight_cache_statistics();
            assert!(bytes <= 16 * 1024 * 1024);
            maximum_hits = maximum_hits.max(hits);
        }
        assert!(maximum_hits > 0, "No repeated patch exercised the cache");
    }
}
