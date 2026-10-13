use nanoleaf_core::palette::{stabilize, TemporalState};
use nanoleaf_core::sampling::SdrSampler;
use serde::Deserialize;

#[derive(Deserialize)]
struct Case {
    pixels: Vec<[u8; 3]>,
    global_cut: bool,
    rgb: [u8; 3],
    algorithm: String,
    dwell: usize,
    pending: String,
    streak: usize,
    confidence: f64,
    held: [f32; 3],
    last_cut: usize,
}

#[test]
fn scene_changes_dark_frames_and_flashes_preserve_temporal_choices() {
    let cases: Vec<Case> =
        serde_json::from_str(include_str!("../../fixtures/palette-temporal.json")).unwrap();
    let sampler = SdrSampler::default();
    let mut state = TemporalState::default();
    for (index, c) in cases.into_iter().enumerate() {
        let frame = sampler.palette_frame(&c.pixels);
        state = stabilize(&frame, &state, c.global_cut, index);
        assert_eq!(state.selected.unwrap().name(), c.algorithm, "frame {index}");
        assert_eq!(
            state.pending.map(|a| a.name()).unwrap_or(""),
            c.pending,
            "frame {index}"
        );
        assert_eq!(
            (state.dwell, state.streak, state.last_scene_cut),
            (c.dwell, c.streak, c.last_cut),
            "frame {index}"
        );
        for channel in 0..3 {
            assert!(
                state.rgb[channel].abs_diff(c.rgb[channel]) <= 1,
                "frame {index}: {:?} vs {:?}",
                state.rgb,
                c.rgb
            );
            assert!(
                (state.held[channel] - c.held[channel]).abs() < 0.003,
                "frame {index}"
            );
        }
        assert!(
            (state.confidence - c.confidence).abs() < 0.00001,
            "frame {index}"
        );
    }
}
