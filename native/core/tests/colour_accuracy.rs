use nanoleaf_core::colour::{apply_profile, decode_srgb, to_oklab, LedCalibration, Style};

fn chroma(rgb: [u8; 3]) -> f32 {
    let [_, a, b] = to_oklab(rgb.map(|v| decode_srgb(f32::from(v))));
    a.hypot(b)
}

#[test]
fn compression_strictly_reduces_saturated_chroma_without_changing_black_or_neutrals() {
    for rgb in [
        [255_u8, 0, 0],
        [0, 255, 0],
        [0, 0, 255],
        [240, 90, 40],
        [80, 140, 220],
    ] {
        let plain = apply_profile(
            rgb.map(f32::from),
            Style::Reference,
            LedCalibration::default(),
        );
        let compressed = apply_profile(
            rgb.map(f32::from),
            Style::Reference,
            LedCalibration {
                chroma_compression: 0.6,
                ..Default::default()
            },
        );
        assert!(
            chroma(compressed) < chroma(plain) * 0.98,
            "{rgb:?}: {plain:?} -> {compressed:?}"
        );
    }
    for style in [
        Style::Reference,
        Style::Ambient,
        Style::Vivid,
        Style::Punchy,
    ] {
        for compression in [0.0, 0.3, 0.6] {
            for code in 0..=255 {
                let actual = apply_profile(
                    [code as f32; 3],
                    style,
                    LedCalibration {
                        chroma_compression: compression,
                        ..Default::default()
                    },
                );
                assert_eq!(
                    actual, [actual[0]; 3],
                    "neutral {code}, compression {compression}"
                );
                if code == 0 {
                    assert_eq!(actual, [0; 3]);
                }
            }
        }
    }
}

// Independent f64 Oklab calculation, using the published transform coefficients,
// for saturated, above-black inputs where the neutral/cartesian blend is zero.
fn compression_reference(rgb: [u8; 3], compression: f64) -> [u8; 3] {
    let [r, g, b] = rgb.map(|v| {
        let x = f64::from(v) / 255.0;
        if x <= 0.04045 {
            x / 12.92
        } else {
            ((x + 0.055) / 1.055).powf(2.4)
        }
    });
    let l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b).cbrt();
    let m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b).cbrt();
    let s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b).cbrt();
    let light = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
    let a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
    let b = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;
    let scale = 1.0 / (1.0 + compression * a.hypot(b));
    let (a, b) = (a * scale, b * scale);
    let l = (light + 0.3963377774 * a + 0.2158037573 * b).powi(3);
    let m = (light - 0.1055613458 * a - 0.0638541728 * b).powi(3);
    let s = (light - 0.0894841775 * a - 1.2914855480 * b).powi(3);
    [
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ]
    .map(|x| {
        let x = x.clamp(0.0, 1.0);
        let encoded = if x <= 0.0031308 {
            12.92 * x
        } else {
            1.055 * x.powf(1.0 / 2.4) - 0.055
        };
        (encoded * 255.0).round_ties_even() as u8
    })
}

#[test]
fn saturated_compression_matches_independent_float64_reference() {
    for rgb in [
        [255_u8, 0, 0],
        [0, 255, 0],
        [0, 0, 255],
        [240, 90, 40],
        [80, 140, 220],
    ] {
        for compression in [0.0, 0.1, 0.3, 0.6] {
            let actual = apply_profile(
                rgb.map(f32::from),
                Style::Reference,
                LedCalibration {
                    chroma_compression: compression,
                    black_cutoff: 0.0,
                    ..Default::default()
                },
            );
            let expected = compression_reference(rgb, f64::from(compression));
            for c in 0..3 {
                assert!(
                    actual[c].abs_diff(expected[c]) <= 1,
                    "{rgb:?} {compression}: {actual:?} != {expected:?}"
                );
            }
        }
    }
}

#[test]
fn vivid_style_changes_chroma_and_neutral_transition_is_continuous() {
    let rgb = [120.0, 40.0, 20.0];
    let plain = apply_profile(rgb, Style::Reference, LedCalibration::default());
    let vivid = apply_profile(rgb, Style::Vivid, LedCalibration::default());
    assert!(
        chroma(vivid) > chroma(plain) * 1.03,
        "{plain:?} -> {vivid:?}"
    );
    let mut previous: Option<[u8; 3]> = None;
    for red in 80..=140 {
        let actual = apply_profile(
            [red as f32, 100.0, 100.0],
            Style::Reference,
            LedCalibration {
                chroma_compression: 0.6,
                ..Default::default()
            },
        );
        if let Some(old) = previous {
            assert!(
                old.iter().zip(actual).all(|(&a, b)| a.abs_diff(b) <= 4),
                "transition {red}: {old:?} -> {actual:?}"
            );
        }
        previous = Some(actual);
    }
}
