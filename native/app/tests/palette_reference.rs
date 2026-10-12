use nanoleaf_core::sampling::SdrSampler;
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
struct Case {
    pixels: Vec<[u8; 3]>,
    best: String,
    rgb: [f32; 3],
    scores: HashMap<String, f64>,
    candidates: HashMap<String, [f32; 3]>,
    saturated: f64,
    neutral: f64,
    highlight: f64,
    dominant_hue: f64,
    coherence: f64,
    rejected_peak: bool,
}

#[test]
fn native_candidates_preserve_reference_colours_scores_and_choices() {
    let cases: Vec<Case> =
        serde_json::from_str(include_str!("../../fixtures/palette-candidates.json")).unwrap();
    let sampler = SdrSampler::default();
    for (index, c) in cases.into_iter().enumerate() {
        let f = sampler.palette_frame(&c.pixels);
        assert_eq!(f.best.name(), c.best, "fixture {index}");
        assert_eq!(f.rejected_peak, c.rejected_peak, "fixture {index}");
        for (actual, expected) in [
            (f.saturated, c.saturated),
            (f.neutral, c.neutral),
            (f.highlight, c.highlight),
            (f.dominant_hue, c.dominant_hue),
            (f.coherence, c.coherence),
        ] {
            assert!(
                (actual - expected).abs() < 0.00001,
                "fixture {index}: {actual} vs {expected}"
            );
        }
        for channel in 0..3 {
            assert!(
                (f32::from(f.rgb[channel]) - c.rgb[channel]).abs() <= 1.0,
                "fixture {index}"
            );
        }
        for (candidate, name) in [
            "area_mean",
            "dominant_saturated_hue",
            "saturated_highlight",
            "peak_luma",
            "previous_colour_hold",
        ]
        .iter()
        .enumerate()
        {
            if let Some(rgb) = c.candidates.get(*name) {
                for (a, b) in f.candidates[candidate].iter().zip(rgb) {
                    assert!((a - b).abs() < 0.002, "fixture {index} {name}: {a} vs {b}");
                }
            }
            if let Some(score) = c.scores.get(*name) {
                assert!(
                    (f.scores[candidate] - score).abs() < 0.00001,
                    "fixture {index} {name}"
                );
            }
        }
    }
}
