use nanoleaf_core::colour::{apply_profile_legacy_oracle, LedCalibration, Style};
use serde::Deserialize;

#[derive(Deserialize)]
struct Data {
    inputs: Vec<[u8; 3]>,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    style: String,
    calibration: Profile,
    expected: Vec<[u8; 3]>,
}
#[derive(Deserialize)]
struct Profile {
    gains: [f32; 3],
    matrix: Vec<f32>,
    white_balance: f32,
    chroma_compression: f32,
    neutral_gain: f32,
    black_cutoff: f32,
    black_knee: f32,
    gamma: f32,
}

#[test]
fn historical_profiles_match_python_oracle_within_one_quantization_code() {
    let data: Data =
        serde_json::from_str(include_str!("../../fixtures/colour-calibration.json")).unwrap();
    let mut differences = 0;
    for case in data.cases {
        let p = case.calibration;
        let cal = LedCalibration {
            gains: p.gains,
            matrix: if p.matrix.len() == 9 {
                Some(std::array::from_fn(|row| {
                    std::array::from_fn(|c| p.matrix[row * 3 + c])
                }))
            } else {
                None
            },
            white_balance: p.white_balance,
            chroma_compression: p.chroma_compression,
            neutral_gain: p.neutral_gain,
            black_cutoff: p.black_cutoff,
            black_knee: p.black_knee,
            gamma: p.gamma,
        };
        let style = match case.style.as_str() {
            "reference" => Style::Reference,
            "ambient" => Style::Ambient,
            "vivid" => Style::Vivid,
            _ => Style::Punchy,
        };
        for (index, (input, expected)) in data.inputs.iter().zip(case.expected).enumerate() {
            let actual = apply_profile_legacy_oracle(input.map(f32::from), style, cal);
            for c in 0..3 {
                let delta = actual[c].abs_diff(expected[c]);
                assert!(
                    delta <= 1,
                    "{} profile {:?}, input {index} {input:?}: {actual:?} vs {expected:?}",
                    case.style,
                    cal
                );
                differences += usize::from(delta > 0);
            }
            if *input == [0; 3] {
                assert_eq!(actual, [0; 3]);
            }
        }
    }
    eprintln!("quantization differences: {differences}");
}
