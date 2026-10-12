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
