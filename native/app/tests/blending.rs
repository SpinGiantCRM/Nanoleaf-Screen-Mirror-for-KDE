use nanoleaf_core::blending::BlendState;
use serde::Deserialize;
#[derive(Deserialize)]
struct Case {
    preset: String,
    spread: String,
    frames: Vec<Frame>,
}
#[derive(Deserialize)]
struct Frame {
    input: Vec<[f32; 3]>,
    previous: Vec<[f32; 3]>,
    expected: Vec<[f32; 3]>,
}
#[test]
fn native_smoothing_and_neighbor_hysteresis_match_reference_sequences() {
    let cases: Vec<Case> =
        serde_json::from_str(include_str!("../../fixtures/blending.json")).unwrap();
    let mut maximum = 0.0_f32;
    for case in cases {
        let mut state = BlendState::default();
        for (index, frame) in case.frames.into_iter().enumerate() {
            let mut actual = frame.input;
            state.neighbors(&mut actual, &case.spread);
            state.smooth(&mut actual, &frame.previous, 0.5, 0.75, &case.preset);
            for (i, (a, e)) in actual.iter().zip(frame.expected).enumerate() {
                for c in 0..3 {
                    let delta = (a[c] - e[c]).abs();
                    maximum = maximum.max(delta);
                    assert!(
                        delta <= 0.002,
                        "{} {} frame {index} zone {i}: {a:?} vs {e:?}",
                        case.preset,
                        case.spread
                    );
                }
            }
        }
    }
    eprintln!("maximum code delta {maximum}");
}
