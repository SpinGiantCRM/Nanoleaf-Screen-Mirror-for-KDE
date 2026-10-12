//! Small-zone colour transforms and measured LED profile processing.
//! Matrix constants preserve the reference's IEEE-754 values, not decimal approximations.

#[derive(Clone, Copy, Debug)]
pub struct LedCalibration {
    pub gains: [f32; 3],
    pub matrix: Option<[[f32; 3]; 3]>,
    pub white_balance: f32,
    pub chroma_compression: f32,
    pub neutral_gain: f32,
    pub black_cutoff: f32,
    pub black_knee: f32,
    pub gamma: f32,
}
impl Default for LedCalibration {
    fn default() -> Self {
        Self {
            gains: [1.0; 3],
            matrix: None,
            white_balance: 0.0,
            chroma_compression: 0.0,
            neutral_gain: 1.0,
            black_cutoff: 0.0032,
            black_knee: 0.0024,
            gamma: 1.0,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub enum Style {
    Reference,
    Ambient,
    Vivid,
    Punchy,
}

const M1: [[u32; 3]; 3] = [
    [0x3ed30eb1, 0x3f094d17, 0x3d52b909],
    [0x3e58fd3b, 0x3f2e4253, 0x3ddbf2f0],
    [0x3db4d7ec, 0x3e903d74, 0x3f214649],
];
const M2: [[u32; 3]; 3] = [
    [0x3e578153, 0x3f4b2a89, 0xbb856ec6],
    [0x3ffd2f0e, 0xc01b6e0e, 0x3ee6b438],
    [0x3cd434b7, 0x3f4863ba, 0xbf4f0560],
];
const M1_INV: [[u32; 3]; 3] = [
    [0x408274ab, 0xc053b18c, 0x3e6c8362],
    [0xbfa25c2d, 0x40270644, 0xbeaec16a],
    [0xbb897f53, 0xbf34133e, 0x3fda931e],
];
const M2_INV: [[u32; 3]; 3] = [
    [0x3f800000, 0x3ecaecc9, 0x3e5cfba9],
    [0x3f800000, 0xbdd8308c, 0xbd82c5fa],
    [0x3f7fffff, 0xbdb7437b, 0xbfa54f66],
];

fn mat(bits: [[u32; 3]; 3], v: [f32; 3]) -> [f32; 3] {
    bits.map(|row| {
        f32::from_bits(row[0]) * v[0]
            + f32::from_bits(row[1]) * v[1]
            + f32::from_bits(row[2]) * v[2]
    })
}
pub fn decode_srgb(encoded: f32) -> f32 {
    let x = (encoded / 255.0).clamp(0.0, 1.0);
    if x <= 0.04045 {
        x / 12.92
    } else {
        ((x + 0.055) / 1.055).powf(2.4)
    }
}
pub fn encode_srgb(linear: f32) -> f32 {
    let x = linear.clamp(0.0, 1.0);
    (if x <= 0.0031308 {
        x * 12.92
    } else {
        1.055 * x.powf(1.0 / 2.4) - 0.055
    })
    .clamp(0.0, 1.0)
        * 255.0
}
pub fn to_oklab(rgb: [f32; 3]) -> [f32; 3] {
    mat(M2, mat(M1, rgb).map(|x| (x.max(0.0) + 1e-8).cbrt()))
}
pub fn from_oklab(lab: [f32; 3]) -> [f32; 3] {
    mat(
        M1_INV,
        mat(M2_INV, lab).map(|x| (x * x * x - 1e-8).max(0.0)),
    )
    .map(|x| x.max(0.0))
}
fn smoothstep(lo: f32, hi: f32, x: f32) -> f32 {
    let t = ((x - lo) / (hi - lo).max(1e-6)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

pub fn apply_profile(rgb: [f32; 3], style: Style, cal: LedCalibration) -> [u8; 3] {
    let mut linear = std::array::from_fn(|c| decode_srgb(rgb[c]) * cal.gains[c].clamp(0.5, 1.5));
    if let Some(matrix) = cal.matrix {
        linear = matrix
            .map(|r| (r[0] * linear[0] + r[1] * linear[1] + r[2] * linear[2]).clamp(0.0, 1.0));
    }
    let wb = cal.white_balance.clamp(-1.0, 1.0);
    let white = if wb >= 0.0 {
        [1.0 + 0.10 * wb, 1.0, 1.0 - 0.06 * wb]
    } else {
        [1.0 + 0.06 * wb, 1.0, 1.0 - 0.10 * wb]
    };
    linear = std::array::from_fn(|c| (linear[c] * white[c]).clamp(0.0, 1.0));
    let y = (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]).clamp(0.0, 1.0);
    let [l, a, b] = to_oklab(linear);
    let c = (a * a + b * b).sqrt();
    let h = b.atan2(a);
    let (boost, cap, compression, cutoff, knee, neutral_threshold, neutral_knee, neutral_luma_gain) =
        match style {
            Style::Reference => (1.0, 1.05, 0.0, 0.0032, 0.0024, 0.016, 0.006, 1.0),
            Style::Ambient => (1.0, 1.08, 0.0, 0.0028, 0.0028, 0.032, 0.012, 1.08),
            Style::Vivid => (1.10, 1.28, 0.07, 0.0018, 0.0018, 0.024, 0.010, 1.04),
            Style::Punchy => (1.20, 1.42, 0.05, 0.0018, 0.0018, 0.022, 0.010, 1.06),
        };
    let neutral_threshold: f32 = neutral_threshold;
    let neutral_knee: f32 = neutral_knee;
    let mut chroma = (c * boost).min(c * cap);
    chroma /= 1.0 + compression * chroma;
    chroma /= 1.0 + cal.chroma_compression.clamp(0.0, 0.6) * chroma;
    let black_gate = smoothstep(cutoff - knee, cutoff + knee, y);
    let neutral = 1.0
        - smoothstep(
            (neutral_threshold - neutral_knee).max(0.0),
            neutral_threshold + neutral_knee,
            c,
        );
    let neutral_l = (y * neutral_luma_gain).clamp(0.0, 1.0).cbrt();
    let mut lum = (neutral_l * neutral + l * (1.0 - neutral)).clamp(0.0, 1.0);
    chroma *= 1.0 - 0.92 * neutral;
    let weight = ((0.03 - chroma) / 0.03).clamp(0.0, 1.0);
    lum = (lum * (1.0 + (cal.neutral_gain.clamp(0.7, 1.5) - 1.0) * weight)).clamp(0.0, 1.0)
        * black_gate;
    chroma *= black_gate;
    let cart = smoothstep(0.03, 0.01, chroma);
    let lab = [
        lum,
        a * cart + chroma * h.cos() * (1.0 - cart),
        b * cart + chroma * h.sin() * (1.0 - cart),
    ];
    let mut out =
        from_oklab(lab).map(|linear| encode_srgb(linear).round_ties_even().clamp(0.0, 255.0));
    let cutoff = cal.black_cutoff.clamp(0.0, 0.03);
    let knee = cal.black_knee.clamp(0.0005, 0.03);
    if cutoff > 0.0 {
        let linear = out.map(decode_srgb);
        let y = (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]).clamp(0.0, 1.0);
        let gate = smoothstep((cutoff - knee).max(0.0), cutoff + knee, y);
        out = out.map(|v| v * gate);
    }
    let gamma = cal.gamma.clamp(1.0, 4.0);
    if (gamma - 1.0).abs() > 1e-6 {
        out = out.map(|v| (v / 255.0).clamp(0.0, 1.0).powf(1.0 / gamma) * 255.0);
    }
    out.map(|v| v.clamp(0.0, 255.0) as u8)
}
