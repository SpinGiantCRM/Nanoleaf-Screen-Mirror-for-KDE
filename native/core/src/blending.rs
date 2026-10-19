//! Temporal/neighbor hysteresis on small zone vectors. Modern mixing operates
//! in linear sRGB before device gamma; the original methods are offline oracles.
use crate::colour::{decode_srgb, encode_srgb, from_oklab, to_oklab};
#[derive(Clone, Default, Debug)]
pub struct ZoneHysteresis {
    tiny: bool,
    damp: bool,
    release: bool,
    neutral_release: bool,
    black: bool,
    jump: bool,
    skip: bool,
    bright: bool,
    hue: bool,
    static_zone: bool,
    chromatic: bool,
    neighbor_dark: bool,
    neighbor_neutral: bool,
    neighbor_block: bool,
}
#[derive(Default, Debug)]
pub struct BlendState {
    pub zones: Vec<ZoneHysteresis>,
    scene: usize,
    initialized: bool,
}
fn peak(v: [f32; 3]) -> f32 {
    v.into_iter().fold(0.0, f32::max)
}
fn chroma(v: [f32; 3]) -> f32 {
    peak(v) - v.into_iter().fold(255.0, f32::min)
}
fn lt(v: f32, enter: f32, exit: f32, old: bool, initialized: bool) -> bool {
    v < if initialized && old { exit } else { enter }
}
fn ge(v: f32, enter: f32, exit: f32, old: bool, initialized: bool) -> bool {
    v >= if initialized && old { exit } else { enter }
}
fn gt(v: f32, enter: f32, exit: f32, old: bool, initialized: bool) -> bool {
    v > if initialized && old { exit } else { enter }
}
fn hue(rgb: [f32; 3], quantize: bool) -> (f32, f32, f32) {
    let rgb = if quantize {
        rgb.map(|v| v.round_ties_even().clamp(0.0, 255.0))
    } else {
        rgb
    };
    let [l, a, b] = to_oklab(rgb.map(decode_srgb));
    (l, (a * a + b * b).sqrt(), b.atan2(a))
}
fn polar_blend(now: [f32; 3], before: [f32; 3], alpha: f32) -> [f32; 3] {
    let (lc, cc, hc) = hue(now, false);
    let (lp, cp, hp) = hue(before, false);
    let h = hp + alpha * (hc - hp).sin().atan2((hc - hp).cos());
    let l = alpha * lc + (1.0 - alpha) * lp;
    let c = alpha * cc + (1.0 - alpha) * cp;
    from_oklab([l, c * h.cos(), c * h.sin()]).map(|v| encode_srgb(v).round_ties_even())
}
enum Mixing {
    Legacy,
    Linear { reference_steps: f32 },
}
/// Convert a 60 Hz reference coefficient into the same exponential time
/// constant at another cadence. Zero elapsed time does not advance history.
pub fn temporal_alpha(alpha: f32, reference_steps: f32) -> f32 {
    let alpha = alpha.clamp(0.0, 1.0);
    if reference_steps <= 0.0 {
        return 0.0;
    }
    if !reference_steps.is_finite() || reference_steps == 1.0 || alpha == 0.0 || alpha == 1.0 {
        return alpha;
    }
    -((-alpha).ln_1p() * reference_steps).exp_m1()
}
impl BlendState {
    fn resize(&mut self, n: usize) {
        if self.zones.len() != n {
            self.zones = vec![ZoneHysteresis::default(); n];
            self.initialized = false;
            self.scene = 0;
        }
    }
    pub fn neighbors(&mut self, colors: &mut [[f32; 3]], mode: &str) {
        self.neighbors_impl(colors, mode, false);
    }
    pub fn neighbors_linear(&mut self, colors: &mut [[f32; 3]], mode: &str) {
        self.neighbors_impl(colors, mode, true);
    }
    fn neighbors_impl(&mut self, colors: &mut [[f32; 3]], mode: &str, linear: bool) {
        let w = match mode {
            "off" => 0.0,
            "precise" => 0.04,
            "soft" => 0.24,
            _ => 0.12,
        };
        if colors.len() < 8 || w == 0.0 {
            return;
        }
        self.resize(colors.len());
        let copy = colors.to_vec();
        let decoded = if linear {
            copy.iter()
                .map(|rgb| rgb.map(decode_srgb))
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        let n = copy.len();
        for (i, rgb) in colors.iter_mut().enumerate() {
            let prev = &mut self.zones[i];
            let p = peak(copy[i]);
            let c = chroma(copy[i]);
            let neutral = lt(p, 40.0, 32.0, prev.neighbor_neutral, self.initialized) && c < 6.0;
            let dark = lt(p, 18.0, 14.0, prev.neighbor_dark, self.initialized) || neutral;
            let a = i.saturating_sub(1);
            let b = (i + 1).min(n - 1);
            let blocked_a = gt(
                peak(copy[a]) - p,
                24.0,
                18.0,
                prev.neighbor_block,
                self.initialized,
            );
            let blocked_b = peak(copy[b]) - p > 24.0;
            let wa = if i == 0 || blocked_a { 0.0 } else { w };
            let wb = if i + 1 == n || blocked_b { 0.0 } else { w };
            if !dark {
                *rgb = std::array::from_fn(|c| {
                    if linear {
                        encode_srgb(
                            (1.0 - wa - wb) * decoded[i][c]
                                + wa * decoded[a][c]
                                + wb * decoded[b][c],
                        )
                    } else {
                        (1.0 - wa - wb) * copy[i][c] + wa * copy[a][c] + wb * copy[b][c]
                    }
                });
            }
            prev.neighbor_neutral = neutral;
            prev.neighbor_dark = dark;
            prev.neighbor_block = blocked_a || blocked_b;
        }
    }
    pub fn smooth(
        &mut self,
        colors: &mut [[f32; 3]],
        previous: &[[f32; 3]],
        smoothing: f32,
        speed: f32,
        preset: &str,
    ) {
        self.smooth_impl(colors, previous, smoothing, speed, preset, Mixing::Legacy);
    }
    pub fn smooth_linear(
        &mut self,
        colors: &mut [[f32; 3]],
        previous: &[[f32; 3]],
        smoothing: f32,
        speed: f32,
        preset: &str,
    ) {
        self.smooth_linear_timed(colors, previous, smoothing, speed, preset, 1.0);
    }
    pub fn smooth_linear_timed(
        &mut self,
        colors: &mut [[f32; 3]],
        previous: &[[f32; 3]],
        smoothing: f32,
        speed: f32,
        preset: &str,
        reference_steps: f32,
    ) {
        self.smooth_impl(
            colors,
            previous,
            smoothing,
            speed,
            preset,
            Mixing::Linear { reference_steps },
        );
    }
    fn smooth_impl(
        &mut self,
        colors: &mut [[f32; 3]],
        previous: &[[f32; 3]],
        smoothing: f32,
        speed: f32,
        preset: &str,
        mixing: Mixing,
    ) {
        if previous.len() != colors.len() || colors.is_empty() {
            return;
        }
        self.resize(colors.len());
        let (dead, tiny, gamma, boost, jump_enter, jump_exit, jump_floor): (
            f32,
            f32,
            f32,
            [f32; 4],
            f32,
            f32,
            f32,
        ) = match preset {
            "calm" => (3.0, 0.03, 1.35, [0.0, 0.16, 0.34, 0.56], 50.0, 42.0, 0.58),
            "dynamic" => (1.2, 0.14, 0.90, [0.04, 0.30, 0.55, 0.84], 34.0, 28.0, 0.84),
            _ => (2.0, 0.08, 1.10, [0.0, 0.22, 0.44, 0.70], 42.0, 36.0, 0.72),
        };
        let deltas: Vec<f32> = colors
            .iter()
            .zip(previous)
            .map(|(a, b)| (0..3).map(|c| (a[c] - b[c]).abs()).sum::<f32>() / 3.0)
            .collect();
        let mut sorted = deltas.clone();
        sorted.sort_by(f32::total_cmp);
        let n = sorted.len();
        let median = if n % 2 == 0 {
            (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
        } else {
            sorted[n / 2]
        };
        let mean = deltas.iter().sum::<f32>() / n as f32;
        self.scene = match self.scene {
            3 => {
                if median >= 18.0 {
                    3
                } else if median >= 6.0 {
                    2
                } else if median >= dead * 0.85 || mean >= dead {
                    1
                } else {
                    0
                }
            }
            2 => {
                if median >= 24.0 {
                    3
                } else if median < 18.0 {
                    if median < 6.0 && mean < dead {
                        0
                    } else {
                        1
                    }
                } else {
                    2
                }
            }
            1 => {
                if median >= 24.0 {
                    3
                } else if median >= 9.0 {
                    1
                } else if median < dead * 0.85 && mean < dead {
                    0
                } else {
                    1
                }
            }
            _ => {
                if median >= 24.0 {
                    3
                } else if median >= 9.0 {
                    1
                } else if median < dead * 1.15 && mean < dead * 1.4 {
                    0
                } else {
                    1
                }
            }
        };
        let gain = (speed / 4.0).clamp(0.0, 1.0).powi(2);
        let minimum = smoothing.clamp(0.0, 1.0);
        for (i, rgb) in colors.iter_mut().enumerate() {
            let cur = *rgb;
            let old = previous[i];
            let p = peak(cur);
            let pp = peak(old);
            let c = chroma(cur);
            let pc = chroma(old);
            let d = deltas[i];
            let h = &mut self.zones[i];
            let init = self.initialized;
            let mut alpha = minimum
                + (1.0 - minimum)
                    * ((d - dead) / (64.0 - dead))
                        .clamp(0.0, 1.0)
                        .powf(gamma)
                        .max(boost[self.scene])
                    * gain;
            let jump = ge(d, jump_enter, jump_exit, h.jump, init);
            if jump {
                alpha = alpha.max(jump_floor * (0.65 + 0.35 * gain));
            }
            let achromatic = c < 4.0;
            let black = lt(p, 8.0, 12.0, h.black, init) && pp > 64.0;
            let release = lt(p, 20.0, 24.0, h.release, init)
                && (pp - p >= 8.0 || (pc >= 4.0 && pp >= 14.0 && pp - p > 4.0));
            let neutral_release =
                lt(p, 40.0, 32.0, h.neutral_release, init) && c < 8.0 && pc >= 8.0 && pp - p > 4.0;
            if black || release || neutral_release {
                alpha = 1.0;
            }
            let tiny_mask = lt(d, dead, dead * 0.25, h.tiny, init);
            let dark_hold = p < 24.0 && pp < 24.0 && tiny_mask && achromatic;
            if dark_hold {
                alpha = 0.0;
            }
            let damp = p < 24.0
                && achromatic
                && lt(d, dead * 2.0, dead * 1.75, h.damp, init)
                && !dark_hold;
            if damp {
                alpha = alpha.min(tiny);
            }
            let skip = if tiny_mask {
                lt(p, 20.0, 24.0, h.skip, init) && (pp >= 20.0 || c >= 4.0 || pc >= 6.0)
            } else {
                false
            };
            if tiny_mask && !skip && !dark_hold && !damp {
                alpha = alpha.min(tiny);
            }
            let bright = gt(p, 20.0, 16.0, h.bright, init) && pp > 20.0 && tiny_mask;
            let oscillation = if bright && c >= 10.0 && pc >= 10.0 {
                let a = hue(cur, true).2 - hue(old, true).2;
                let hue_delta = a.sin().atan2(a.cos()).abs();
                gt(hue_delta, 0.35, 0.30, h.hue, init)
            } else {
                false
            };
            if oscillation {
                alpha = alpha.min(tiny);
            }
            let static_zone = lt(d, dead * 1.5, dead * 1.2, h.static_zone, init);
            let chromatic = static_zone && ge(c, 10.0, 8.0, h.chromatic, init) && pc >= 10.0;
            *rgb = if let Mixing::Linear { reference_steps } = mixing {
                // Full responsiveness disables smoothing, including the tiny-
                // change caps that otherwise override the user's coefficient.
                if minimum == 1.0 {
                    alpha = 1.0;
                }
                alpha = temporal_alpha(alpha, reference_steps);
                if alpha == 0.0 || cur == old {
                    old
                } else if alpha == 1.0 {
                    cur
                } else {
                    std::array::from_fn(|c| {
                        encode_srgb(
                            (1.0 - alpha) * decode_srgb(old[c]) + alpha * decode_srgb(cur[c]),
                        )
                    })
                }
            } else if chromatic {
                polar_blend(cur, old, alpha)
            } else {
                std::array::from_fn(|c| old[c] + alpha * (cur[c] - old[c]))
            };
            h.tiny = tiny_mask;
            h.damp = damp;
            h.release = release;
            h.neutral_release = neutral_release;
            h.black = black;
            h.jump = jump;
            h.skip = skip;
            h.bright = bright;
            h.hue = oscillation;
            h.static_zone = static_zone;
            h.chromatic = chromatic;
        }
        self.initialized = true;
    }
}
