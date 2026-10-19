use nanoleaf_native::{capture::Frame, config::Config, pipeline::Pipeline};
fn config() -> Config {
    let mut c = Config {
        device_zone_count: 4,
        color_style: "reference".into(),
        zone_temporal_accumulation: false,
        letterbox_detection: false,
        blue_noise_dither: true,
        ..Default::default()
    };
    c.calibration.corner_anchor_top_left = 0;
    c.calibration.corner_anchor_top_right = 1;
    c.calibration.corner_anchor_bottom_right = 2;
    c.calibration.corner_anchor_bottom_left = 3;
    c
}
fn frame(rgb: [u8; 3]) -> Frame {
    Frame {
        width: 32,
        height: 24,
        pixels: rgb.repeat(32 * 24),
    }
}

#[test]
fn fast_response_recreates_calibrated_source_on_first_changed_update() {
    use std::time::Duration;
    for fps in [30, 60, 120] {
        for gamma in [1.0, 2.2] {
            let mut c = config();
            c.fps = fps;
            c.zone_temporal_accumulation = true;
            c.smoothing = 0.5;
            c.led_calibration_profile_sdr.red_gain = 0.87;
            c.led_calibration_profile_sdr.green_gain = 1.08;
            c.led_calibration_profile_sdr.blue_gain = 0.95;
            c.led_calibration_profile_sdr.led_gamma = gamma;
            c.enable_fast_response();
            let mut p = Pipeline::default();
            for rgb in [
                [64; 3],
                [192; 3],
                [128; 3],
                [132; 3],
                [180, 40, 20],
                [20, 60, 200],
                [0; 3],
            ] {
                let expected = Pipeline::default().process(&frame(rgb), &c).unwrap();
                p.set_temporal_elapsed(Duration::from_secs_f64(1.0 / f64::from(fps)));
                let actual = p.process(&frame(rgb), &c).unwrap();
                assert_eq!(
                    actual.unquantized_rgb, expected.unquantized_rgb,
                    "fps{fps} gamma{gamma} {rgb:?}"
                );
            }
        }
    }
}
#[test]
fn device_gamma_is_applied_after_temporal_mixing_and_brightness() {
    for gamma in [1.0, 1.5, 2.2, 4.0] {
        let mut c = config();
        c.brightness = 0.6;
        let mut corrected = c.clone();
        corrected.led_calibration_profile_sdr.led_gamma = gamma;
        let (mut plain, mut adjusted) = (Pipeline::default(), Pipeline::default());
        for rgb in [
            [128, 128, 128],
            [192, 80, 40],
            [80, 120, 180],
            [150, 60, 80],
            [0, 0, 0],
            [255, 255, 255],
        ] {
            let a = plain.process(&frame(rgb), &c).unwrap();
            let b = adjusted.process(&frame(rgb), &corrected).unwrap();
            for (a, b) in a.unquantized_rgb.iter().zip(b.unquantized_rgb) {
                for k in 0..3 {
                    let expected = if gamma == 1.0 {
                        f64::from(a[k])
                    } else {
                        (f64::from(a[k]) / 255.0).powf(1.0 / gamma) * 255.0
                    };
                    assert!(
                        (f64::from(b[k]) - expected).abs() < 0.0001,
                        "gamma{gamma} {rgb:?}: {a:?} {b:?}"
                    );
                }
            }
        }
    }
}
#[test]
fn black_cut_cannot_be_overridden_by_small_integer_ack_hold() {
    let mut c = config();
    c.blue_noise_dither = false;
    for code in [0, 1, 2] {
        let mut p = Pipeline::default();
        p.process(&frame([128; 3]), &c).unwrap();
        p.override_sent(&[[1; 3]; 4]);
        let out = p.process(&frame([code; 3]), &c).unwrap();
        assert_eq!(out.colors, vec![[0; 3]; 4], "source code {code}");
        assert_eq!(out.unquantized_rgb, vec![[0.0; 3]; 4]);
    }
}

#[test]
fn low_motion_accumulation_matches_elapsed_time_across_capture_cadences() {
    use std::time::Duration;
    let mut c = config();
    c.zone_temporal_accumulation = true;
    c.smoothing = 1.0;
    c.smoothing_speed = 0.0;
    let mut dense = Pipeline::default();
    let mut sparse = Pipeline::default();
    dense.process(&frame([128; 3]), &c).unwrap();
    sparse.process(&frame([128; 3]), &c).unwrap();
    let mut a = None;
    let mut b = None;
    for _ in 0..10 {
        dense.set_temporal_elapsed(Duration::from_secs_f64(1.0 / 60.0));
        a = Some(dense.process(&frame([129; 3]), &c).unwrap());
    }
    for _ in 0..5 {
        sparse.set_temporal_elapsed(Duration::from_secs_f64(1.0 / 30.0));
        b = Some(sparse.process(&frame([129; 3]), &c).unwrap());
    }
    let a = a.unwrap();
    let b = b.unwrap();
    let decode = |v: f64| ((v / 255.0 + 0.055) / 1.055).powf(2.4);
    let target = decode(128.0) + (decode(129.0) - decode(128.0)) * (1.0 - 0.95_f64.powi(10));
    let expected = (1.055 * target.powf(1.0 / 2.4) - 0.055) * 255.0;
    assert!((f64::from(a.unquantized_rgb[0][0]) - expected).abs() < 0.0002);
    assert!((a.unquantized_rgb[0][0] - b.unquantized_rgb[0][0]).abs() < 0.0001);
    sparse.set_temporal_elapsed(Duration::ZERO);
    let paused = sparse.process(&frame([129; 3]), &c).unwrap();
    assert_eq!(paused.unquantized_rgb, b.unquantized_rgb);
    sparse.set_temporal_elapsed(Duration::ZERO);
    assert_eq!(
        sparse.process(&frame([0; 3]), &c).unwrap().colors,
        vec![[0; 3]; 4]
    );
}
