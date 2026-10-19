use nanoleaf_core::blending::BlendState;

// Independent double-precision IEC sRGB equations, without production helpers.
fn decode(v: f64) -> f64 {
    let v = v / 255.0;
    if v <= 0.04045 {
        v / 12.92
    } else {
        ((v + 0.055) / 1.055).powf(2.4)
    }
}
fn encode(v: f64) -> f64 {
    255.0
        * if v <= 0.0031308 {
            12.92 * v
        } else {
            1.055 * v.powf(1.0 / 2.4) - 0.055
        }
}
#[test]
fn half_step_preserves_linear_energy_instead_of_encoded_average() {
    let mut actual = [[192.0; 3]];
    BlendState::default().smooth_linear(&mut actual, &[[64.0; 3]], 0.5, 0.0, "responsive");
    let expected = encode(0.5 * decode(64.0) + 0.5 * decode(192.0));
    assert!((f64::from(actual[0][0]) - expected).abs() < 0.0001);
    assert_eq!(actual[0], [actual[0][0]; 3]);
    assert!(actual[0][0] > 140.0); // Encoded-space averaging would be 128.
}
#[test]
fn neighbor_mixing_matches_energy_reference_and_keeps_black_off() {
    for (mode, weight) in [("precise", 0.04), ("balanced", 0.12), ("soft", 0.24)] {
        let mut actual = vec![[128.0; 3]; 8];
        actual[2] = [120.0, 60.0, 40.0];
        actual[4] = [140.0, 100.0, 80.0];
        actual[6] = [0.0; 3];
        BlendState::default().neighbors_linear(&mut actual, mode);
        for (c, (a, b)) in [120.0, 60.0, 40.0]
            .into_iter()
            .zip([140.0, 100.0, 80.0])
            .enumerate()
        {
            let expected = encode(
                (1.0 - 2.0 * weight) * decode(128.0) + weight * decode(a) + weight * decode(b),
            );
            assert!(
                (f64::from(actual[3][c]) - expected).abs() < 0.0001,
                "{mode} {actual:?}"
            );
        }
        assert_eq!(actual[6], [0.0; 3]);
    }
}
#[test]
fn neutral_codes_stay_neutral_and_static_fractional_colours_are_not_rounded() {
    for code in 0..=255 {
        let mut actual = [[code as f32; 3]];
        let previous = actual;
        let mut state = BlendState::default();
        for _ in 0..16 {
            state.smooth_linear(&mut actual, &previous, 0.5, 0.75, "responsive");
            assert_eq!(actual, previous);
        }
    }
    let previous = [[150.125, 55.375, 40.25]];
    let mut actual = previous;
    BlendState::default().smooth_linear(&mut actual, &previous, 0.5, 0.75, "responsive");
    assert_eq!(actual, previous);
    actual = [[154.0, 55.0, 40.0]];
    BlendState::default().smooth_linear(
        &mut actual,
        &[[150.0, 55.0, 40.0]],
        0.5,
        0.0,
        "responsive",
    );
    let expected = encode(0.92 * decode(150.0) + 0.08 * decode(154.0));
    assert!((f64::from(actual[0][0]) - expected).abs() < 0.0001);
    assert_ne!(actual[0][0], actual[0][0].round());
}

#[test]
fn elapsed_alpha_matches_exponential_reference_and_partitioned_intervals() {
    use nanoleaf_core::blending::temporal_alpha;
    for alpha in [0.0_f32, 0.03, 0.05, 0.35, 0.5, 0.92, 1.0] {
        for steps in [0.0_f32, 0.25, 0.5, 1.0, 2.0, 6.0, 120.0] {
            let actual = temporal_alpha(alpha, steps);
            let expected = if steps == 0.0 {
                0.0
            } else {
                1.0 - (1.0 - f64::from(alpha)).powf(f64::from(steps))
            };
            assert!((f64::from(actual) - expected).abs() < 0.000001);
            let half = temporal_alpha(alpha, steps / 2.0);
            assert!((actual - (1.0 - (1.0 - half).powi(2))).abs() < 0.000001);
        }
    }
    assert_eq!(temporal_alpha(0.5, f32::NAN), 0.5);
}

#[test]
fn two_source_periods_have_same_energy_as_one_dropped_frame_interval() {
    let mut dense = [[192.0; 3]];
    let mut state = BlendState::default();
    state.smooth_linear_timed(&mut dense, &[[64.0; 3]], 0.5, 0.0, "responsive", 1.0);
    let old = dense;
    dense = [[192.0; 3]];
    state.smooth_linear_timed(&mut dense, &old, 0.5, 0.0, "responsive", 1.0);
    let mut sparse = [[192.0; 3]];
    BlendState::default().smooth_linear_timed(
        &mut sparse,
        &[[64.0; 3]],
        0.5,
        0.0,
        "responsive",
        2.0,
    );
    assert!((dense[0][0] - sparse[0][0]).abs() < 0.0001);
}
