//! SDR adaptive prepass: mixed-content classification and its dark-biased mean.
//! Native decision path and guarded Python bridge path share reduction ordering.
//! Borderline floating decisions explicitly defer to the reference implementation.

use crate::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MixedDecision {
    Clear = 0,
    Mixed = 1,
    Reference = 2,
}

#[derive(Debug, Clone, Copy)]
pub struct AdaptiveSample {
    pub decision: MixedDecision,
    pub mixed_rgb: [u8; 3],
}

#[derive(Clone, Copy)]
struct Pixel {
    rgb: [f32; 3],
    lum: f32,
    sat: f32,
}

const MARGIN: f32 = 0.00001;

impl SdrSampler {
    pub fn adaptive_prepass(&self, frame: &SdrRgb8Frame<'_>, zone: ZoneRect) -> AdaptiveSample {
        self.adaptive(frame, zone, true)
    }

    /// Fully native evaluation, including decisions near float/quantization boundaries.
    pub fn adaptive_native(&self, frame: &SdrRgb8Frame<'_>, zone: ZoneRect) -> AdaptiveSample {
        self.adaptive(frame, zone, false)
    }

    fn adaptive(&self, frame: &SdrRgb8Frame<'_>, zone: ZoneRect, guarded: bool) -> AdaptiveSample {
        let empty = AdaptiveSample {
            decision: MixedDecision::Clear,
            mixed_rgb: [0; 3],
        };
        if zone.width <= 0 || zone.height <= 0 {
            return empty;
        }
        let x = zone.x.clamp(0, frame.width as i64) as usize;
        let y = zone.y.clamp(0, frame.height as i64) as usize;
        let width = (zone.width as u64).min((frame.width - x) as u64) as usize;
        let height = (zone.height as u64).min((frame.height - y) as u64) as usize;
        if width == 0 || height == 0 {
            return empty;
        }
        // Cap transient feature storage even for a single full-screen source zone.
        // Oversized patches preserve the Python decision/mean for this zone.
        if guarded && width * height > 1_048_576 {
            return AdaptiveSample {
                decision: MixedDecision::Reference,
                mixed_rgb: [0; 3],
            };
        }
        // At most one zone's feature storage lives at once, not full-frame FP32
        // integral/cumsum buffers. Geometry is bounded by the validated byte view.
        let mut pixels = Vec::with_capacity(width * height);
        let mut lumas = Vec::with_capacity(width * height);
        let mut sums = [0.0_f32; 3];
        for row in y..y + height {
            let offset = row * frame.stride + x * 3;
            for codes in frame.data[offset..offset + width * 3].chunks_exact(3) {
                let rgb = std::array::from_fn(|c| self.linear_codes[usize::from(codes[c])]);
                for c in 0..3 {
                    sums[c] += rgb[c];
                }
                let max = rgb[0].max(rgb[1]).max(rgb[2]);
                let min = rgb[0].min(rgb[1]).min(rgb[2]);
                let lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
                let sat = (max - min) / max.max(0.0001);
                pixels.push(Pixel { rgb, lum, sat });
                lumas.push(lum);
            }
        }
        let n = pixels.len() as f32;
        let mean_lum = pairwise_sum(&lumas) / n;
        let deviations: Vec<_> = lumas.iter().map(|lum| (lum - mean_lum).powi(2)).collect();
        let std = (pairwise_sum(&deviations) / n).sqrt();
        let decision = if guarded && (std - 0.042).abs() <= MARGIN {
            MixedDecision::Reference
        } else if std > 0.042 {
            MixedDecision::Mixed
        } else {
            classify_subtle(&pixels, mean_lum, std, guarded)
        };
        if decision != MixedDecision::Mixed {
            return AdaptiveSample {
                decision,
                mixed_rgb: [0; 3],
            };
        }
        let middle = lumas.len() / 2;
        lumas.select_nth_unstable_by(middle, f32::total_cmp);
        let median = if lumas.len() % 2 == 0 {
            let lower = lumas[..middle]
                .iter()
                .copied()
                .fold(f32::NEG_INFINITY, f32::max);
            (lower + lumas[middle]) / 2.0
        } else {
            lumas[middle]
        };
        let mut rgb = sums.map(|sum| sum / n);
        if guarded && (median - 0.0058).abs() <= MARGIN {
            return AdaptiveSample {
                decision: MixedDecision::Reference,
                mixed_rgb: [0; 3],
            };
        }
        if median < 0.0058 {
            let weights: Vec<_> = pixels
                .iter()
                .map(|pixel| {
                    let weight = 1.0 / (1.0 + pixel.lum * 100.0);
                    weight * weight
                })
                .collect();
            let weight_sum = pairwise_sum(&weights);
            if weight_sum > 1e-6 {
                let mut weighted = [0.0_f32; 3];
                for (pixel, weight) in pixels.iter().zip(weights) {
                    for (c, sum) in weighted.iter_mut().enumerate() {
                        *sum += pixel.rgb[c] * weight;
                    }
                }
                rgb = weighted.map(|sum| sum / weight_sum);
            }
        }
        let encoded = rgb.map(encode_float);
        // Preserve the reference at quantization boundaries, too. This also
        // avoids propagating a one-code difference through temporal decisions.
        if guarded
            && encoded
                .iter()
                .any(|code| (code.fract() - 0.5).abs() < 0.002)
        {
            return AdaptiveSample {
                decision: MixedDecision::Reference,
                mixed_rgb: [0; 3],
            };
        }
        AdaptiveSample {
            decision,
            mixed_rgb: encoded.map(|code| code.round_ties_even() as u8),
        }
    }
}

fn classify_subtle(pixels: &[Pixel], mean_lum: f32, std: f32, guarded: bool) -> MixedDecision {
    let delta = 0.003 + 0.038 * mean_lum;
    let mut prominent = 0;
    let mut max_sat = 0.0_f32;
    for pixel in pixels {
        let prominence = ((pixel.lum - mean_lum) / delta).clamp(0.0, 1.0);
        if guarded && (prominence - 0.5).abs() <= MARGIN * 10.0 {
            return MixedDecision::Reference;
        }
        if prominence > 0.5 {
            prominent += 1;
        }
        max_sat = max_sat.max(pixel.sat);
    }
    if prominent as f64 / (pixels.len() as f64) < 0.15 && max_sat > 0.25 {
        if guarded && (std - 0.017).abs() <= MARGIN {
            return MixedDecision::Reference;
        }
        if std > 0.017 {
            return MixedDecision::Mixed;
        }
    }
    let hues: Vec<_> = pixels
        .iter()
        .filter(|pixel| pixel.sat > 0.2)
        .map(|pixel| hue(pixel.rgb))
        .collect();
    if hues.len() < 8 {
        return MixedDecision::Clear;
    }
    let sin: Vec<_> = hues.iter().map(|angle| angle.sin()).collect();
    let cos: Vec<_> = hues.iter().map(|angle| angle.cos()).collect();
    let mean_sin = pairwise_sum(&sin) / hues.len() as f32;
    let mean_cos = pairwise_sum(&cos) / hues.len() as f32;
    let coherence = (mean_sin * mean_sin + mean_cos * mean_cos).sqrt();
    if guarded && (coherence - 0.85).abs() <= MARGIN {
        return MixedDecision::Reference;
    }
    if coherence < 0.85 {
        MixedDecision::Mixed
    } else {
        MixedDecision::Clear
    }
}

fn hue(rgb: [f32; 3]) -> f32 {
    let [r, g, b] = rgb;
    let max = r.max(g).max(b);
    let delta = max - r.min(g).min(b);
    if delta <= 1e-6 {
        return 0.0;
    }
    let h = if max == r {
        ((g - b) / delta).rem_euclid(6.0)
    } else if max == g {
        2.0 + (b - r) / delta
    } else {
        4.0 + (r - g) / delta
    };
    h * (std::f32::consts::PI / 3.0)
}

fn encode_float(linear: f32) -> f32 {
    let linear = linear.clamp(0.0, 1.0);
    let encoded = if linear <= 0.0031308 {
        linear * 12.92
    } else {
        1.055 * linear.powf(1.0 / 2.4) - 0.055
    };
    (encoded.clamp(0.0, 1.0) * 255.0).clamp(0.0, 255.0)
}

// Adapted from NumPy's pairwise reduction ordering; see THIRD_PARTY_NOTICES.md.
// Match the reference's contiguous float32 reductions: eight accumulators in
// blocks of 128, recursively split on an eight-element boundary. Channel means
// above instead preserve the reference's strided, sequential RGB summation.
pub(crate) fn pairwise_sum(values: &[f32]) -> f32 {
    let n = values.len();
    if n < 8 {
        return values.iter().fold(-0.0_f32, |sum, value| sum + value);
    }
    if n <= 128 {
        let mut sums: [f32; 8] = values[..8].try_into().expect("eight values checked");
        let end = n - n % 8;
        for chunk in values[8..end].chunks_exact(8) {
            for lane in 0..8 {
                sums[lane] += chunk[lane];
            }
        }
        let mut sum = ((sums[0] + sums[1]) + (sums[2] + sums[3]))
            + ((sums[4] + sums[5]) + (sums[6] + sums[7]));
        for value in &values[end..] {
            sum += value;
        }
        sum
    } else {
        let middle = (n / 2) - (n / 2) % 8;
        pairwise_sum(&values[..middle]) + pairwise_sum(&values[middle..])
    }
}
