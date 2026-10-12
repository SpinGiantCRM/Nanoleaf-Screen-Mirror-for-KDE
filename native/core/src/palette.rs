//! Native palette candidates/scoring. Per-zone inputs are explicitly SDR RGB8.
use crate::adaptive::pairwise_sum;
use crate::colour::encode_srgb;
use crate::sampling::SdrSampler;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Algorithm {
    Area = 0,
    Dominant = 1,
    Highlight = 2,
    Peak = 3,
    Hold = 4,
}
impl Algorithm {
    pub fn name(self) -> &'static str {
        match self {
            Self::Area => "area_mean",
            Self::Dominant => "dominant_saturated_hue",
            Self::Highlight => "saturated_highlight",
            Self::Peak => "peak_luma",
            Self::Hold => "previous_colour_hold",
        }
    }
}
const ALGORITHMS: [Algorithm; 5] = [
    Algorithm::Area,
    Algorithm::Dominant,
    Algorithm::Highlight,
    Algorithm::Peak,
    Algorithm::Hold,
];

pub struct PaletteFrame {
    pub area_only: bool,
    pub candidates: [[f32; 3]; 5],
    pub scores: [f64; 5],
    pub best: Algorithm,
    pub rgb: [u8; 3],
    pub saturated: f64,
    pub neutral: f64,
    pub highlight: f64,
    pub dominant_hue: f64,
    pub coherence: f64,
    pub rejected_peak: bool,
}

#[derive(Clone, Debug, Default)]
pub struct TemporalState {
    pub selected: Option<Algorithm>,
    pub confidence: f64,
    pub rgb: [u8; 3],
    pub dominant_hue: f64,
    pub dwell: usize,
    pub pending: Option<Algorithm>,
    pub streak: usize,
    pub held: [f32; 3],
    pub last_scene_cut: usize,
}

fn chroma(rgb: [f32; 3]) -> f32 {
    rgb.into_iter().fold(0.0_f32, f32::max) - rgb.into_iter().fold(255.0_f32, f32::min)
}
fn delta(a: [f32; 3], b: [f32; 3]) -> f32 {
    (0..3).map(|c| (a[c] - b[c]).abs()).sum::<f32>() / 3.0
}
fn single_hue(rgb: [f32; 3]) -> f64 {
    let [r, g, b] = rgb.map(f64::from);
    let max = r.max(g).max(b);
    let delta = max - r.min(g).min(b);
    if delta <= 1.0 {
        return 0.0;
    }
    let h = if max == r {
        ((g - b) / delta).rem_euclid(6.0)
    } else if max == g {
        2.0 + (b - r) / delta
    } else {
        4.0 + (r - g) / delta
    };
    h * 60.0
}

pub fn stabilize(
    frame: &PaletteFrame,
    prev: &TemporalState,
    global_cut: bool,
    index: usize,
) -> TemporalState {
    let instant = frame.rgb.map(f32::from);
    let previous = prev.rgb.map(f32::from);
    let difference = delta(instant, previous);
    let had_previous = prev.selected.is_some();
    let scene_cut = global_cut
        || had_previous
            && (difference >= 64.0
                || difference >= 48.0
                    && (frame.scores[frame.best as usize] >= 0.30
                        || frame.saturated >= 0.20 && frame.coherence >= 0.65));
    let old = prev.selected.unwrap_or(frame.best);
    let previous_confidence = prev
        .selected
        .and_then(|a| {
            (!frame.area_only || a == Algorithm::Area).then_some(frame.scores[a as usize])
        })
        .unwrap_or(prev.confidence);
    let margin = frame.scores[frame.best as usize] - previous_confidence;
    let required: usize = if margin >= 0.45 {
        3
    } else if margin >= 0.30 {
        4
    } else if margin >= 0.20 {
        5
    } else {
        6
    };
    let mut selected = old;
    let mut blocked = false;
    let mut pending = None;
    let mut streak = 0;
    let mut dwell = 0;
    if !had_previous || scene_cut {
        selected = frame.best;
    } else if frame.best != old {
        if margin < 0.15 {
            blocked = true;
            dwell = required;
        } else {
            streak = if prev.pending == Some(frame.best) {
                prev.streak + 1
            } else {
                1
            };
            pending = Some(frame.best);
            dwell = required.saturating_sub(streak);
            if streak >= required {
                selected = frame.best;
                streak = 0;
                pending = None;
                dwell = 0;
            } else {
                blocked = true;
            }
        }
    }
    let mut target = frame.candidates[selected as usize];
    let prev_source = if prev.held == [0.0; 3] {
        previous
    } else {
        prev.held
    };
    if !scene_cut
        && chroma(prev_source) >= 22.0
        && chroma(target) <= 15.0
        && frame.neutral >= 0.18
        && chroma(instant) <= 15.0
    {
        target = prev_source;
        selected = old;
        blocked = true;
    }
    if !scene_cut && selected != old {
        let difference = (single_hue(previous) - single_hue(target)).abs() % 360.0;
        if chroma(previous) >= 22.0
            && chroma(target) >= 22.0
            && difference.min(360.0 - difference) >= 35.0
            && margin < 0.30
        {
            target = previous;
            selected = old;
            blocked = true;
        }
    }
    let prev_held = if prev.held == [0.0; 3] {
        previous
    } else {
        prev.held
    };
    if !scene_cut
        && had_previous
        && (blocked || selected == old)
        && delta(instant, previous) > 28.0
        && margin < 0.15
    {
        target = prev_held;
        blocked = true;
    }
    let held = if !had_previous || scene_cut || prev_held == [0.0; 3] {
        target
    } else {
        let difference: [f32; 3] = std::array::from_fn(|c| target[c] - prev_held[c]);
        let step = difference
            .iter()
            .copied()
            .map(f32::abs)
            .fold(0.0_f32, f32::max);
        let max_step = if blocked { 20.0 } else { 42.0 };
        if step <= max_step {
            target
        } else {
            std::array::from_fn(|c| prev_held[c] + difference[c] * (max_step / step))
        }
    };
    TemporalState {
        selected: Some(selected),
        confidence: if frame.area_only && selected != Algorithm::Area {
            frame.scores[frame.best as usize]
        } else {
            frame.scores[selected as usize]
        },
        rgb: held.map(|v| v.round_ties_even().clamp(0.0, 255.0) as u8),
        dominant_hue: frame.dominant_hue,
        dwell,
        pending,
        streak,
        held,
        last_scene_cut: if scene_cut {
            index
        } else {
            prev.last_scene_cut
        },
    }
}

struct Pixel {
    rgb: [f32; 3],
    lum: f32,
    sat: f32,
    max: f32,
    neutral: bool,
}
impl Pixel {
    fn meaningful(&self) -> bool {
        self.sat >= 0.18 && self.lum >= 0.0116 && self.max >= 0.0168
    }
}

fn average<'a>(pixels: impl Iterator<Item = &'a Pixel>) -> [f32; 3] {
    let mut rgb = [0.0; 3];
    let mut n = 0;
    for pixel in pixels {
        for (sum, v) in rgb.iter_mut().zip(pixel.rgb) {
            *sum += v;
        }
        n += 1;
    }
    if n == 0 {
        [0.0; 3]
    } else {
        rgb.map(|v| v / n as f32)
    }
}
fn hue_degrees(rgb: [f32; 3]) -> f32 {
    let [r, g, b] = rgb;
    let max = r.max(g).max(b);
    let delta = max - r.min(g).min(b);
    if delta <= 1e-6 {
        return 0.0;
    }
    let h = if max == r {
        ((g - b) / delta).rem_euclid(6.0)
    } else if max == g {
        (2.0 + (b - r) / delta).rem_euclid(6.0)
    } else {
        (4.0 + (r - g) / delta).rem_euclid(6.0)
    };
    h * 60.0
}

impl SdrSampler {
    pub fn palette_frame(&self, codes: &[[u8; 3]]) -> PaletteFrame {
        let low = codes.iter().flatten().copied().max().unwrap_or(0) < 32;
        let pixels: Vec<_> = codes
            .iter()
            .map(|code| {
                let rgb = code.map(|v| self.linear_codes[v as usize]);
                let max = rgb[0].max(rgb[1]).max(rgb[2]);
                let min = rgb[0].min(rgb[1]).min(rgb[2]);
                let lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
                let sat = (max - min) / max.max(0.0001);
                Pixel {
                    rgb,
                    lum,
                    sat,
                    max,
                    neutral: sat < 0.10 && (lum > 0.456 || min > 0.578),
                }
            })
            .collect();
        let area = average(pixels.iter());
        if low {
            let rgb = area.map(|v| encode_srgb(v).round_ties_even() as u8);
            let encoded = rgb.map(f32::from);
            return PaletteFrame {
                area_only: true,
                candidates: [encoded; 5],
                scores: [
                    if pixels.is_empty() { 0.0 } else { 1.0 },
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                ],
                best: Algorithm::Area,
                rgb,
                saturated: 0.0,
                neutral: 0.0,
                highlight: 0.0,
                dominant_hue: 0.0,
                coherence: 0.0,
                rejected_peak: false,
            };
        }
        let n = pixels.len() as f64;
        let saturated = pixels.iter().filter(|p| p.meaningful()).count() as f64 / n;
        let neutral = pixels.iter().filter(|p| p.neutral).count() as f64 / n;
        let lumas: Vec<_> = pixels.iter().map(|p| p.lum).collect();
        let mean_lum = pairwise_sum(&lumas) / pixels.len() as f32;
        let deviations: Vec<_> = lumas.iter().map(|v| (v - mean_lum).powi(2)).collect();
        let std = (pairwise_sum(&deviations) / pixels.len() as f32).sqrt();
        let contrast = (f64::from(std) / 0.082).clamp(0.0, 1.0);
        let mut counts = [0_usize; 18];
        for p in pixels.iter().filter(|p| p.meaningful()) {
            counts[(hue_degrees(p.rgb) / 20.0).floor() as usize % 18] += 1;
        }
        let best_bin = (0..18)
            .max_by_key(|&i| (counts[i], std::cmp::Reverse(i)))
            .unwrap_or(0);
        let dominant_pixels: Vec<_> = pixels
            .iter()
            .filter(|p| {
                p.meaningful() && (hue_degrees(p.rgb) / 20.0).floor() as usize % 18 == best_bin
            })
            .collect();
        let dominant = if dominant_pixels.is_empty() {
            area
        } else {
            average(dominant_pixels.iter().copied())
        };
        let (dominant_hue, coherence) = if dominant_pixels.is_empty() {
            (0.0, 0.0)
        } else {
            let rad: Vec<_> = dominant_pixels
                .iter()
                .map(|p| hue_degrees(p.rgb) * (std::f32::consts::PI / 180.0))
                .collect();
            let sin: Vec<_> = rad.iter().map(|a| a.sin()).collect();
            let cos: Vec<_> = rad.iter().map(|a| a.cos()).collect();
            let s = pairwise_sum(&sin) / sin.len() as f32;
            let c = pairwise_sum(&cos) / cos.len() as f32;
            (
                (best_bin * 20 + 10) as f64,
                f64::from((s * s + c * c).sqrt()),
            )
        };
        let selected: Vec<_> = pixels
            .iter()
            .filter(|p| p.meaningful() && p.lum >= 0.021_f32.max(mean_lum + 0.005) && !p.neutral)
            .collect();
        let highlight = selected.len() as f64 / n;
        let highlighted = if selected.is_empty() {
            area
        } else {
            let weights: Vec<_> = selected
                .iter()
                .map(|p| p.sat * ((p.lum - mean_lum) / 0.08).clamp(0.2, 1.5))
                .collect();
            let total = pairwise_sum(&weights);
            if total <= 1e-6 {
                average(selected.iter().copied())
            } else {
                let mut sums = [0.0; 3];
                for (p, w) in selected.iter().zip(weights) {
                    for (c, sum) in sums.iter_mut().enumerate() {
                        *sum += p.rgb[c] * w;
                    }
                }
                sums.map(|v| v / total)
            }
        };
        let mut ordered = lumas.clone();
        ordered.sort_unstable_by(f32::total_cmp);
        let index = (ordered.len() - 1) as f64 * 0.75;
        let base = index.floor() as usize;
        let fraction = index - base as f64;
        let cutoff = (f64::from(ordered[base])
            + (f64::from(ordered[index.ceil() as usize]) - f64::from(ordered[base])) * fraction)
            as f32;
        let peak: Vec<_> = pixels.iter().filter(|p| p.lum >= cutoff).collect();
        let peak_coverage = peak.len() as f64 / n;
        let rejected_peak = peak.iter().filter(|p| p.neutral).count() as f64 / peak.len() as f64
            > 0.55
            || peak.iter().filter(|p| p.meaningful()).count() as f64 / (peak.len() as f64) < 0.20;
        let candidates = [
            area,
            dominant,
            highlighted,
            average(peak.iter().copied()),
            area,
        ]
        .map(|rgb| rgb.map(encode_srgb));
        let max = candidates[1].iter().copied().fold(0.0_f32, f32::max);
        let min = candidates[1].iter().copied().fold(255.0_f32, f32::min);
        let proxy = f64::from(max - min) / f64::from(max.max(1.0));
        let scores = [
            (0.35 - saturated * 0.55 - highlight * 0.15 + neutral * 0.20).max(0.0),
            if saturated < 0.06 {
                0.05
            } else {
                saturated * 1.4 + coherence * 0.75 - neutral * 0.35 + (proxy * 0.4).min(0.25)
            },
            if highlight < 0.02 {
                0.05
            } else {
                let s = highlight * 1.15 + saturated * 0.55 + contrast * 0.25 - neutral * 0.60;
                if neutral > 0.45 && highlight < 0.12 {
                    s * 0.2
                } else {
                    s
                }
            },
            if rejected_peak {
                0.0
            } else {
                peak_coverage * 0.7 + saturated * 0.3 + contrast * 0.2
            },
            0.0,
        ];
        let best = *ALGORITHMS
            .iter()
            .max_by(|&&a, &&b| {
                scores[a as usize]
                    .total_cmp(&scores[b as usize])
                    .then(b.name().cmp(a.name()))
            })
            .unwrap();
        let rgb = candidates[best as usize].map(|v| v.round_ties_even().clamp(0.0, 255.0) as u8);
        PaletteFrame {
            area_only: false,
            candidates,
            scores,
            best,
            rgb,
            saturated,
            neutral,
            highlight,
            dominant_hue,
            coherence,
            rejected_peak,
        }
    }
}

impl SdrSampler {
    /// Explicit vivid/dynamic analyzer; default/reference/ambient skip this stage.
    pub fn analyze_dynamic(
        &self,
        codes: &[[u8; 3]],
        sampled: [u8; 3],
        previous: Option<[u8; 3]>,
        hyper: bool,
    ) -> [u8; 3] {
        if codes.is_empty() {
            return sampled;
        }
        let mut linear_mean = [0.0_f32; 3];
        let mut peak = 0.0_f32;
        for code in codes {
            for c in 0..3 {
                let x = self.linear_codes[code[c] as usize];
                linear_mean[c] += x;
                peak = peak.max(x);
            }
        }
        linear_mean = linear_mean.map(|v| v / codes.len() as f32);
        if peak < 0.021 && chroma(linear_mean) < 0.006 {
            return linear_mean.map(|v| encode_srgb(v).round_ties_even() as u8);
        }
        let lumas: Vec<f32> = codes
            .iter()
            .map(|c| 0.2126 * c[0] as f32 + 0.7152 * c[1] as f32 + 0.0722 * c[2] as f32)
            .collect();
        let mean = pairwise_sum(&lumas) / codes.len() as f32;
        let dev: Vec<_> = lumas.iter().map(|v| (v - mean).powi(2)).collect();
        let contrast = ((pairwise_sum(&dev) / codes.len() as f32).sqrt() / 64.0).clamp(0.0, 1.0);
        let norm = mean / 255.0;
        let required = 10.0 + 55.0 * norm;
        let prominence: Vec<_> = lumas
            .iter()
            .map(|l| {
                ((l - mean) / required)
                    .clamp(0.0, 1.0)
                    .powf(1.0 + 1.2 * norm)
            })
            .collect();
        let weights: Vec<_> = codes
            .iter()
            .zip(&lumas)
            .zip(&prominence)
            .map(|((c, l), p)| {
                let max = *c.iter().max().unwrap() as f32;
                let min = *c.iter().min().unwrap() as f32;
                let sat = (max - min) / max.max(1.0);
                (0.30
                    + if hyper { 0.58 } else { 0.50 } * sat
                    + 0.20 * (l / 255.0).powf(0.7).clamp(0.0, 1.0))
                    * p
                    * (1.0 - 0.18 * (1.0 - sat).clamp(0.0, 1.0) * (1.0 - p).clamp(0.0, 1.0))
            })
            .collect();
        let total = pairwise_sum(&weights);
        let mut highlight = [0.0; 3];
        for (i, code) in codes.iter().enumerate() {
            for c in 0..3 {
                highlight[c] += code[c] as f32 * if total > 0.0 { weights[i] } else { 1.0 };
            }
        }
        highlight = highlight.map(|v| {
            v / if total > 0.0 {
                total
            } else {
                codes.len() as f32
            }
        });
        let motion = previous
            .map(|old| {
                ((0..3)
                    .map(|c| f32::from(sampled[c].abs_diff(old[c])))
                    .sum::<f32>()
                    / 3.0
                    / 255.0
                    * 1.8)
                    .clamp(0.0, 1.0)
            })
            .unwrap_or(0.0);
        let standout = (pairwise_sum(&prominence) / codes.len() as f32).clamp(0.0, 1.0);
        let mix = if hyper {
            0.28 + 0.38 * contrast + 0.36 * motion + 0.34 * standout
        } else {
            0.22 + 0.34 * contrast + 0.32 * motion + 0.28 * standout
        }
        .clamp(0.10, if hyper { 0.88 } else { 0.78 });
        let mut candidate =
            std::array::from_fn(|c| (1.0 - mix) * sampled[c] as f32 + mix * highlight[c]);
        if let Some(old) = previous {
            let step = if hyper { 95.0 } else { 78.0 } + 90.0 * motion;
            let blend = if hyper { 0.42 } else { 0.38 };
            candidate = std::array::from_fn(|c| {
                let p = old[c] as f32;
                let target = p + (candidate[c] - p).clamp(-step, step);
                (1.0 - blend) * p + blend * target
            });
        }
        candidate.map(|v| v.round_ties_even().clamp(0.0, 255.0) as u8)
    }
}
