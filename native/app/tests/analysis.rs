use nanoleaf_core::sampling::SdrSampler;
use nanoleaf_native::{
    analysis,
    capture::Frame,
    config::{Config, Rect},
    pipeline::{direct_plan, Pipeline},
};
#[test]
fn appearance_samplers_preserve_every_uniform_neutral_and_primary() {
    let s = SdrSampler::default();
    for x in 0..=255 {
        for rgb in [[x; 3], [x, 0, 0], [0, x, 0], [0, 0, x]] {
            let patch = vec![rgb; 99];
            assert_eq!(analysis::multi_moment(&s, &patch).unwrap(), rgb);
            assert_eq!(analysis::wavelet(&s, &patch, 11).unwrap(), rgb);
        }
    }
    let mut patch = vec![[255, 10, 2]; 70];
    patch.extend(vec![[0, 30, 250]; 30]);
    // Old bin-centre method returns [240,16,16], inventing green/blue.
    assert_eq!(analysis::multi_moment(&s, &patch).unwrap(), [255, 10, 2]);
}
fn config() -> Config {
    let mut c = Config {
        device_zone_count: 4,
        letterbox_detection: false,
        blue_noise_dither: false,
        zone_temporal_accumulation: false,
        sampling_quality: "high".into(),
        ..Default::default()
    };
    c.calibration.corner_anchor_top_left = 0;
    c.calibration.corner_anchor_top_right = 1;
    c.calibration.corner_anchor_bottom_right = 2;
    c.calibration.corner_anchor_bottom_left = 3;
    c
}
#[test]
fn reference_ignores_appearance_policies_and_keeps_direct_gpu_eligibility() {
    let mut c = config();
    c.color_style = "reference".into();
    let frame = Frame {
        width: 64,
        height: 48,
        pixels: (0..64 * 48 * 3).map(|i| (i % 256) as u8).collect(),
    };
    let expected = Pipeline::default().process(&frame, &c).unwrap();
    c.multi_moment_zone_colors = true;
    c.scene_adaptive_profiles = true;
    c.virtual_zone_oversample = 512;
    c.sampling_mode = "wavelet".into();
    assert!(direct_plan(&c, 64, 48).is_ok());
    let actual = Pipeline::default().process(&frame, &c).unwrap();
    assert_eq!(actual.sampled, expected.sampled);
    assert_eq!(actual.colors, expected.colors);
}
#[test]
fn every_optional_pixel_policy_applies_privacy_before_sampling_and_preserves_manual_count() {
    for mode in ["wavelet", "area_average", "palette_adaptive"] {
        let mut c = config();
        c.sampling_mode = mode.into();
        c.multi_moment_zone_colors = true;
        c.virtual_zone_oversample = 512;
        c.scene_adaptive_profiles = true;
        c.privacy_zones = vec![Rect {
            x: 0.0,
            y: 0.0,
            w: 1.0,
            h: 1.0,
        }];
        let frame = Frame {
            width: 64,
            height: 48,
            pixels: vec![255; 64 * 48 * 3],
        };
        let out = Pipeline::default().process(&frame, &c).unwrap();
        assert_eq!(out.sampled, vec![[0; 3]; 4]);
        assert_eq!(out.colors, vec![[0; 3]; 4]);
        assert!(direct_plan(&c, 64, 48).is_err());
    }
}
