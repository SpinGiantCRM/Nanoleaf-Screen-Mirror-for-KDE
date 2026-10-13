use nanoleaf_native::{
    config::Config,
    prediction::{enabled, Predictor},
};
use std::time::{Duration, Instant};
fn config() -> Config {
    Config {
        sync_mode: "4d".into(),
        blue_noise_dither: false,
        ..Default::default()
    }
}
fn history(p: &mut Predictor, t: Instant, samples: [[u8; 3]; 3]) {
    for (i, rgb) in samples.into_iter().enumerate() {
        p.observe(&[rgb; 48], t + Duration::from_millis(i as u64 * 33));
    }
}
#[test]
fn slow_ramp_adds_one_bounded_packet_without_recursive_extrapolation() {
    let t = Instant::now();
    let c = config();
    let mut p = Predictor::default();
    history(&mut p, t, [[96, 48, 0], [100, 52, 0], [104, 56, 0]]);
    assert!(p.predict(&c, t + Duration::from_millis(82)).is_none());
    let out = p.predict(&c, t + Duration::from_millis(83)).unwrap();
    assert_eq!(out, vec![[105, 57, 0]; 48]);
    assert!(p.predict(&c, t + Duration::from_millis(99)).is_none());
    p.observe(&[[108, 60, 0]; 48], t + Duration::from_millis(99));
    assert_eq!(
        p.predict(&c, t + Duration::from_millis(116)).unwrap(),
        vec![[109, 61, 0]; 48]
    );
}
#[test]
fn reference_accuracy_dither_zero_strength_and_standard_are_exact_bypasses() {
    let c = config();
    assert!(enabled(&c));
    let mut cases = vec![];
    for style in ["reference", "natural"] {
        let mut v = c.clone();
        v.color_style = style.into();
        cases.push(v);
    }
    let mut v = c.clone();
    v.accuracy_mode = true;
    cases.push(v);
    let mut v = c.clone();
    v.blue_noise_dither = true;
    cases.push(v);
    let mut v = c.clone();
    v.predictive_sync_strength = 0.0;
    cases.push(v);
    let mut v = c.clone();
    v.sync_mode = "standard".into();
    cases.push(v);
    for c in cases {
        let t = Instant::now();
        let mut p = Predictor::default();
        history(&mut p, t, [[96; 3], [100; 3], [104; 3]]);
        assert!(!enabled(&c));
        assert!(p.predict(&c, t + Duration::from_millis(83)).is_none());
    }
}
#[test]
fn darkening_black_cuts_stalls_jitter_reset_and_shape_changes_suppress_prediction() {
    let c = config();
    let t = Instant::now();
    for samples in [
        [[0; 3]; 3],
        [[100; 3], [96; 3], [92; 3]],
        [[20; 3], [24; 3], [28; 3]],
        [[80; 3], [84; 3], [255; 3]],
        [[80; 3], [84; 3], [80; 3]],
    ] {
        let mut p = Predictor::default();
        history(&mut p, t, samples);
        assert!(p.predict(&c, t + Duration::from_millis(83)).is_none());
    }
    let mut p = Predictor::default();
    history(&mut p, t, [[96; 3], [100; 3], [104; 3]]);
    assert!(p.predict(&c, t + Duration::from_millis(180)).is_none());
    p.reset();
    assert!(p.predict(&c, t + Duration::from_millis(83)).is_none());
    history(&mut p, t, [[96; 3], [100; 3], [104; 3]]);
    p.observe(&[[108; 3]], t + Duration::from_millis(99));
    assert!(p.deadline(&c).is_none());
    history(&mut p, t, [[96; 3], [100; 3], [104; 3]]);
    p.observe(&[[108; 3]; 48], t + Duration::from_millis(116));
    assert!(p.deadline(&c).is_none());
}
#[test]
fn all_neutral_ramps_remain_neutral_black_off_and_each_channel_within_one_code() {
    let c = config();
    let t = Instant::now();
    for x in 0..=247 {
        let mut p = Predictor::default();
        history(&mut p, t, [[x; 3], [x + 4; 3], [x + 8; 3]]);
        if let Some(out) = p.predict(&c, t + Duration::from_millis(83)) {
            for v in out {
                assert_eq!(v, [v[0]; 3]);
                assert!(v[0].abs_diff(x + 8) <= 1);
            }
        }
    }
}

#[test]
fn busy_usb_never_trades_next_real_frame_latency_for_a_prediction() {
    let c = config();
    let t = Instant::now();
    for budget in [8, 17, 250] {
        let mut p = Predictor::default();
        history(&mut p, t, [[96; 3], [100; 3], [104; 3]]);
        assert!(p
            .predict_with_budget(
                &c,
                t + Duration::from_millis(83),
                Duration::from_millis(budget)
            )
            .is_none());
    }
    let mut p = Predictor::default();
    history(&mut p, t, [[96; 3], [100; 3], [104; 3]]);
    assert_eq!(
        p.predict_with_budget(&c, t + Duration::from_millis(83), Duration::from_millis(4))
            .unwrap(),
        vec![[105; 3]; 48]
    );
}
