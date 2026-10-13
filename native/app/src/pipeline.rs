//! Stateful single-strip processing. Capture pixels carry an explicit SDR contract.
use crate::{capture::Frame, config::Config, geometry};
use anyhow::{ensure, Result};
use nanoleaf_core::{
    adaptive::MixedDecision,
    blending::BlendState,
    colour::{self, LedCalibration, Style},
    palette::{self, Algorithm, TemporalState},
    sampling::{SdrRgb8Frame, SdrSampler, ZoneRect},
};
use serde::Serialize;
use std::time::Instant;

#[derive(Default, Clone, Debug, Serialize)]
pub struct ProcessingTimes {
    pub sampling_ms: f64,
    pub colour_ms: f64,
    pub mixed_ms: f64,
    pub palette_ms: f64,
    pub total_ms: f64,
}
#[derive(Default)]
pub struct Pipeline {
    sampler: SdrSampler,
    palette: Vec<TemporalState>,
    accumulation: Vec<[f64; 3]>,
    previous_sample: Vec<[u8; 3]>,
    previous_smooth: Vec<[f32; 3]>,
    previous_sent: Vec<[u8; 3]>,
    dark_hold: Vec<bool>,
    quant_hold: Vec<bool>,
    blend: BlendState,
    frame_index: usize,
    motion: f64,
}
pub struct Output {
    pub colors: Vec<[u8; 3]>,
    pub sampled: Vec<[u8; 3]>,
    pub modes: Vec<String>,
    pub times: ProcessingTimes,
}
fn luma(rgb: [f32; 3]) -> f32 {
    0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
}
fn smoothstep(lo: f32, hi: f32, x: f32) -> f32 {
    let t = ((x - lo) / (hi - lo).max(1e-6)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}
fn calibration(c: &Config) -> LedCalibration {
    // KWin raw screenshots are display-referred sRGB, including HDR desktops.
    // Never decode these bytes as PQ or adapt them from panel primaries again.
    let p = &c.led_calibration_profile_sdr;
    LedCalibration {
        gains: [p.red_gain as f32, p.green_gain as f32, p.blue_gain as f32],
        matrix: if p.color_matrix.len() == 9 {
            Some(std::array::from_fn(|r| {
                std::array::from_fn(|c| p.color_matrix[r * 3 + c].clamp(-4.0, 4.0) as f32)
            }))
        } else {
            None
        },
        white_balance: p.white_balance_temperature as f32,
        chroma_compression: p.chroma_compression as f32,
        neutral_gain: p.neutral_luminance_gain as f32,
        black_cutoff: p.black_luminance_cutoff as f32,
        black_knee: p.black_luminance_knee as f32,
        gamma: p.led_gamma as f32,
    }
}
fn mask(frame: &Frame, c: &Config) -> Option<Vec<u8>> {
    if c.privacy_zones.is_empty() {
        return None;
    }
    let mut data = frame.pixels.clone();
    let w = frame.width;
    let h = frame.height;
    for z in &c.privacy_zones {
        let x = (z.x.clamp(0.0, 1.0) * w as f64) as usize;
        let y = (z.y.clamp(0.0, 1.0) * h as f64) as usize;
        let x1 = ((z.x + z.w).clamp(0.0, 1.0) * w as f64) as usize;
        let y1 = ((z.y + z.h).clamp(0.0, 1.0) * h as f64) as usize;
        if x1 > x && y1 > y {
            for row in y..y1 {
                data[(row * w + x) * 3..(row * w + x1) * 3].fill(0);
            }
        }
    }
    Some(data)
}
fn content_zones(frame: &Frame, zones: &mut [ZoneRect]) -> bool {
    let (w, h) = (frame.width, frame.height);
    let rgb = |x: usize, y: usize| {
        let o = (y * w + x) * 3;
        luma([
            frame.pixels[o] as f32,
            frame.pixels[o + 1] as f32,
            frame.pixels[o + 2] as f32,
        ])
    };
    let row = |y: usize| (0..w).map(|x| rgb(x, y)).sum::<f32>() / w as f32;
    let top = (0..h).step_by(8).find(|&y| row(y) > 4.0).unwrap_or(0);
    let bottom = (top + 1..h)
        .rev()
        .step_by(8)
        .find(|&y| row(y) > 4.0)
        .map(|y| y + 1)
        .unwrap_or(h);
    let col = |x: usize| (top..bottom).map(|y| rgb(x, y)).sum::<f32>() / (bottom - top) as f32;
    let left = (0..w).step_by(8).find(|&x| col(x) > 4.0).unwrap_or(0);
    let right = (left + 1..w)
        .rev()
        .step_by(8)
        .find(|&x| col(x) > 4.0)
        .map(|x| x + 1)
        .unwrap_or(w);
    let horizontal = top as f64 / h as f64 >= 0.08 && (h - bottom) as f64 / h as f64 >= 0.08;
    let vertical = left as f64 / w as f64 >= 0.08 && (w - right) as f64 / w as f64 >= 0.08;
    if !(horizontal || vertical)
        || ((right - left) * (bottom - top)) as f64 / (w * h) as f64 >= 0.85
    {
        return false;
    }
    let (l, t, r, b) = (left as i64, top as i64, right as i64, bottom as i64);
    for z in zones {
        let x = z.x.max(l);
        let y = z.y.max(t);
        let x1 = (z.x + z.width).min(r);
        let y1 = (z.y + z.height).min(b);
        if x1 > x && y1 > y {
            z.x = x;
            z.y = y;
            z.width = x1 - x;
            z.height = y1 - y;
        } else if z.y + z.height <= t {
            z.y = t;
            z.height = z.height.min(b - t).max(1);
        } else if z.y >= b {
            z.y = (b - z.height.max(1)).max(t);
            z.height = z.height.min(b - t).max(1);
        } else if z.x + z.width <= l {
            z.x = l;
            z.width = z.width.min(r - l).max(1);
        } else if z.x >= r {
            z.x = (r - z.width.max(1)).max(l);
            z.width = z.width.min(r - l).max(1);
        }
    }
    true
}
fn anchor(mut z: ZoneRect, w: usize, h: usize) -> ZoneRect {
    let pw = ((z.width as f64 * 0.3) as i64).max(1);
    let ph = ((z.height as f64 * 0.3) as i64).max(1);
    if z.x <= 0 {
        z.x = (z.x - pw).max(0);
        z.width = (w as i64 - z.x).min(z.width + pw);
    }
    if z.y <= 0 {
        z.y = (z.y - ph).max(0);
        z.height = (h as i64 - z.y).min(z.height + ph);
    }
    z
}
/// Reject unverified policies and incomplete physical mapping before opening USB.
/// Loading/editing such configurations remains supported and non-destructive.
pub fn validate_mirroring(c: &Config) -> Result<()> {
    c.validate()?;
    ensure!(
        !c.multi_moment_zone_colors && c.virtual_zone_oversample == 0 && !c.scene_adaptive_profiles,
        "This optional analysis is awaiting native parity verification; use the Python fallback"
    );
    let accuracy = c.accuracy_mode || matches!(c.color_style.as_str(), "reference" | "natural");
    ensure!(
        accuracy
            || matches!(
                c.sampling_mode.as_str(),
                "auto" | "palette_adaptive" | "edge_direct" | "area_average"
            ),
        "Sampling mode {} awaits native verification; use the Python fallback",
        c.sampling_mode
    );
    ensure!(
        accuracy || c.sync_mode != "4d",
        "Predictive colour output awaits native validation; use the Python fallback"
    );
    ensure!(
        (4..=512).contains(&c.device_zone_count),
        "Complete strip setup with a manual count and four corner anchors"
    );
    let mut anchors = c.anchors();
    anchors.sort_unstable();
    ensure!(
        anchors[0] >= 0
            && anchors[3] < c.device_zone_count as i64
            && anchors.windows(2).all(|a| a[0] != a[1]),
        "Complete four distinct corner anchors before mirroring"
    );
    Ok(())
}
impl Pipeline {
    /// Quantization history must reflect acknowledged output, not queued frames.
    pub fn override_sent(&mut self, sent: &[[u8; 3]]) {
        if self.previous_sent != sent {
            self.quant_hold.fill(false);
            self.previous_sent = sent.to_vec();
        }
    }
    pub fn process(&mut self, frame: &Frame, c: &Config) -> Result<Output> {
        validate_mirroring(c)?;
        ensure!(
            frame.width > 0 && frame.height > 0,
            "Empty capture geometry"
        );
        ensure!(
            frame.pixels.len()
                == frame
                    .width
                    .checked_mul(frame.height)
                    .and_then(|v| v.checked_mul(3))
                    .unwrap_or(0),
            "Invalid RGB frame"
        );
        // Unported optional analysis never silently changes a user's colour policy.
        ensure!(!c.multi_moment_zone_colors&&c.virtual_zone_oversample==0&&!c.scene_adaptive_profiles,"This optional analysis is awaiting native parity verification; use the Python fallback");
        let started = Instant::now();
        let (mut zones, counts) = geometry::pixel_zones(c, frame.width, frame.height)?;
        let mapping = geometry::calibrated_mapping(c, zones.len(), counts)?;
        let letterbox = c.letterbox_detection && content_zones(frame, &mut zones);
        let accuracy = c.accuracy_mode || matches!(c.color_style.as_str(), "reference" | "natural");
        let mut mode = if accuracy {
            "edge_direct"
        } else if c.sampling_mode == "auto" {
            "palette_adaptive"
        } else {
            &c.sampling_mode
        };
        if !accuracy && mode == "palette_adaptive" {
            let mut peaks: Vec<u8> = self
                .previous_sample
                .iter()
                .map(|v| *v.iter().max().unwrap())
                .collect();
            peaks.sort_unstable();
            let low = !peaks.is_empty()
                && (f32::from(peaks[(peaks.len() - 1) / 2]) + f32::from(peaks[peaks.len() / 2]))
                    / 2.0
                    < 40.0;
            if letterbox || low {
                mode = "area_average";
            }
        }
        ensure!(
            matches!(mode, "palette_adaptive" | "edge_direct" | "area_average"),
            "Sampling mode {mode} awaits native verification; use the Python fallback"
        );
        let masked = mask(frame, c);
        let bytes = masked.as_deref().unwrap_or(&frame.pixels);
        let view = SdrRgb8Frame::new(bytes, frame.width, frame.height, frame.width * 3)?;
        if self.palette.len() != zones.len() {
            self.palette = vec![TemporalState::default(); zones.len()];
        }
        let stride = if accuracy {
            1
        } else {
            match c.sampling_quality.as_str() {
                "high" => 1,
                "low" => 4,
                _ => 2,
            }
        };
        let mut mixed_ms = 0.0;
        let mut palette_ms = 0.0;
        let mut raw = Vec::with_capacity(zones.len());
        let mut modes = Vec::with_capacity(zones.len());
        for (index, z) in zones.into_iter().enumerate() {
            if mode != "palette_adaptive" && c.zone_box_filter_sampling {
                let z = if c.zone_box_filter_sampling {
                    anchor(z, frame.width, frame.height)
                } else {
                    z
                };
                raw.push(self.sampler.sample_zone(&view, z).srgb);
                modes.push(mode.to_string());
                continue;
            }
            let x = z.x.clamp(0, frame.width as i64) as usize;
            let y = z.y.clamp(0, frame.height as i64) as usize;
            let x1 = (z.x + z.width).clamp(x as i64, frame.width as i64) as usize;
            let y1 = (z.y + z.height).clamp(y as i64, frame.height as i64) as usize;
            // Preserve reference rounding of source geometry on the stepped image.
            let sw = (frame.width as f64 / stride as f64)
                .round_ties_even()
                .max(1.0) as usize;
            let sh = (frame.height as f64 / stride as f64)
                .round_ties_even()
                .max(1.0) as usize;
            let sx = (x as f64 / stride as f64).round_ties_even().min(sw as f64) as usize;
            let sy = (y as f64 / stride as f64).round_ties_even().min(sh as f64) as usize;
            let x1 = (sx + ((x1 - x) as f64 / stride as f64).ceil().max(1.0) as usize)
                .min(sw)
                .min(frame.width.div_ceil(stride))
                * stride;
            let y1 = (sy + ((y1 - y) as f64 / stride as f64).ceil().max(1.0) as usize)
                .min(sh)
                .min(frame.height.div_ceil(stride))
                * stride;
            let x = (sx * stride).min(x1);
            let y = (sy * stride).min(y1);
            let mut patch =
                Vec::with_capacity((x1 - x).div_ceil(stride) * (y1 - y).div_ceil(stride));
            for row in (y..y1).step_by(stride) {
                for col in (x..x1).step_by(stride) {
                    let i = (row * frame.width + col) * 3;
                    patch.push([bytes[i], bytes[i + 1], bytes[i + 2]]);
                }
            }
            if mode != "palette_adaptive" {
                let pw = (x1 - x).div_ceil(stride);
                let ph = (y1 - y).div_ceil(stride);
                let weights =
                    crate::spatial::weights([sx, sy, pw, ph], [sw, sh], mode, &c.edge_locality);
                let color = if let Some(weights) = weights {
                    self.sampler.weighted_mean(&patch, &weights)?
                } else if patch.is_empty() {
                    [0; 3]
                } else {
                    let flat: Vec<_> = patch.iter().flatten().copied().collect();
                    let v = SdrRgb8Frame::new(&flat, patch.len(), 1, patch.len() * 3)?;
                    self.sampler
                        .sample_zone(
                            &v,
                            ZoneRect {
                                x: 0,
                                y: 0,
                                width: patch.len() as i64,
                                height: 1,
                            },
                        )
                        .srgb
                };
                raw.push(color);
                modes.push(mode.to_string());
                continue;
            }
            let (mut color, name) = if patch.is_empty() {
                ([0; 3], "area_mean".to_string())
            } else {
                let uniform = patch.iter().all(|p| *p == patch[0]);
                let phase = Instant::now();
                let mixed = if uniform {
                    nanoleaf_core::adaptive::AdaptiveSample {
                        decision: MixedDecision::Clear,
                        mixed_rgb: [0; 3],
                    }
                } else {
                    let flat: Vec<u8> = patch.iter().flatten().copied().collect();
                    let patch_view = SdrRgb8Frame::new(&flat, patch.len(), 1, patch.len() * 3)?;
                    self.sampler.adaptive_native(
                        &patch_view,
                        ZoneRect {
                            x: 0,
                            y: 0,
                            width: patch.len() as i64,
                            height: 1,
                        },
                    )
                };
                mixed_ms += phase.elapsed().as_secs_f64() * 1000.0;
                if mixed.decision == MixedDecision::Mixed {
                    let rgb = mixed.mixed_rgb;
                    self.palette[index] = TemporalState {
                        selected: Some(Algorithm::Area),
                        confidence: 1.0,
                        rgb,
                        held: rgb.map(f32::from),
                        dominant_hue: self.palette[index].dominant_hue,
                        ..Default::default()
                    };
                    (rgb, "area_mean".to_string())
                } else {
                    let phase = Instant::now();
                    let pf = self
                        .sampler
                        .palette_frame(if uniform { &patch[..1] } else { &patch });
                    let mut temporal = palette::stabilize(
                        &pf,
                        &self.palette[index],
                        self.motion >= 24.0,
                        self.frame_index,
                    );
                    let rgb = temporal.rgb;
                    let name = temporal.selected.unwrap().name().to_string();
                    // The existing runtime serializes palette history between frames.
                    temporal.held = temporal.held.map(|v| (v * 100.0).round_ties_even() / 100.0);
                    temporal.confidence =
                        (temporal.confidence * 10000.0).round_ties_even() / 10000.0;
                    self.palette[index] = temporal;
                    palette_ms += phase.elapsed().as_secs_f64() * 1000.0;
                    (rgb, name)
                }
            };
            if !accuracy && matches!(c.color_style.as_str(), "vivid" | "punchy") {
                color = self.sampler.analyze_dynamic(
                    &patch,
                    color,
                    self.previous_sample.get(index).copied(),
                    c.color_style == "punchy" && c.motion_preset == "dynamic",
                );
            }
            raw.push(color);
            modes.push(name);
        }
        if std::env::var_os("NATIVE_TRACE").is_some() && self.frame_index == 7 {
            eprintln!("raw modes {:?} {:?}", raw, modes);
        }
        if mode != "palette_adaptive" {
            self.palette.fill(TemporalState::default());
        }
        if c.zone_temporal_accumulation {
            if self.accumulation.len() != raw.len() {
                self.accumulation = raw.iter().map(|v| v.map(f64::from)).collect();
            } else {
                let a = 0.05 + 0.45 * (self.motion / 64.0).clamp(0.0, 1.0);
                for (acc, rgb) in self.accumulation.iter_mut().zip(&raw) {
                    for k in 0..3 {
                        acc[k] = (1.0 - a) * acc[k] + a * f64::from(rgb[k]);
                    }
                }
            }
            raw = self
                .accumulation
                .iter()
                .map(|v| v.map(|x| x.round_ties_even().clamp(0.0, 255.0) as u8))
                .collect();
        }
        let sampling_ms = started.elapsed().as_secs_f64() * 1000.0;
        self.motion = if self.previous_sample.len() == raw.len() {
            let mut differences: Vec<f32> = raw
                .iter()
                .zip(&self.previous_sample)
                .map(|(a, b)| (0..3).map(|k| f32::from(a[k].abs_diff(b[k]))).sum::<f32>() / 3.0)
                .collect();
            differences.sort_by(f32::total_cmp);
            let n = differences.len();
            if n.is_multiple_of(2) {
                f64::from((differences[n / 2 - 1] + differences[n / 2]) / 2.0)
            } else {
                f64::from(differences[n / 2])
            }
        } else {
            0.0
        };
        self.previous_sample = raw.clone();
        let mut mapped: Vec<[f32; 3]> =
            mapping.into_iter().map(|i| raw[i].map(f32::from)).collect();
        if self.dark_hold.len() != mapped.len() {
            self.dark_hold = vec![false; mapped.len()];
        }
        for (i, rgb) in mapped.iter_mut().enumerate() {
            let y = luma(rgb.map(colour::decode_srgb));
            let held = if self.frame_index == 0 {
                y < 0.008
            } else if self.dark_hold[i] {
                y <= 0.025
            } else {
                y < 0.008
            };
            self.dark_hold[i] = held;
            if held {
                let gray = colour::encode_srgb(y).round_ties_even();
                *rgb = [gray; 3];
            }
        }
        let style = match c.color_style.as_str() {
            "reference" | "natural" => Style::Reference,
            "vivid" => Style::Vivid,
            "punchy" => Style::Punchy,
            _ => Style::Ambient,
        };
        let cal = calibration(c);
        for rgb in &mut mapped {
            *rgb = colour::apply_profile(*rgb, style, cal).map(f32::from);
        }
        if !accuracy {
            self.blend.neighbors(&mut mapped, &c.light_spread);
        }
        if c.brightness != 1.0 {
            for rgb in &mut mapped {
                *rgb =
                    rgb.map(|x| colour::encode_srgb(colour::decode_srgb(x) * c.brightness as f32));
            }
        }
        let (preset, minimum, speed) = if accuracy {
            (
                "responsive",
                c.smoothing.max(0.35),
                c.smoothing_speed.max(0.5),
            )
        } else {
            let (a, b) = match c.motion_preset.as_str() {
                "calm" => (0.75, 0.70),
                "dynamic" => (1.15, 1.35),
                _ => (1.0, 1.0),
            };
            (
                c.motion_preset.as_str(),
                (c.smoothing * a).clamp(0.0, 1.0),
                (c.smoothing_speed * b).clamp(0.0, 4.0),
            )
        };
        self.blend.smooth(
            &mut mapped,
            &self.previous_smooth,
            minimum as f32,
            speed as f32,
            preset,
        );
        for rgb in &mut mapped {
            let peak = rgb.iter().copied().fold(0.0, f32::max);
            let gray = colour::encode_srgb(luma(rgb.map(colour::decode_srgb))).round_ties_even();
            let achro = 1.0 - smoothstep(12.0, 20.0, peak);
            let off = smoothstep(4.0, 16.0, peak);
            *rgb = rgb.map(|x| (x * (1.0 - achro) + gray * achro) * off);
        }
        self.previous_smooth = mapped.clone();
        if self.quant_hold.len() != mapped.len() {
            self.quant_hold = vec![false; mapped.len()];
        }
        // Holding an integer output before temporal quantization destroys its
        // fractional duty cycle. Use the legacy hold only when dither is off.
        if !c.blue_noise_dither && self.previous_sent.len() == mapped.len() {
            for (i, rgb) in mapped.iter_mut().enumerate() {
                let old = self.previous_sent[i].map(f32::from);
                let delta = (0..3).map(|k| (rgb[k] - old[k]).abs()).fold(0.0, f32::max);
                let threshold =
                    (60.0 / c.fps as f32).max(1.25) * if self.quant_hold[i] { 0.8 } else { 1.0 };
                self.quant_hold[i] = delta < threshold;
                if self.quant_hold[i] {
                    *rgb = old;
                }
            }
        }
        let colors = mapped
            .iter()
            .enumerate()
            .map(|(i, rgb)| quantize(*rgb, c.blue_noise_dither, self.frame_index, i))
            .collect::<Vec<_>>();
        self.previous_sent = colors.clone();
        self.frame_index += 1;
        let total_ms = started.elapsed().as_secs_f64() * 1000.0;
        Ok(Output {
            colors,
            sampled: raw,
            modes,
            times: ProcessingTimes {
                sampling_ms,
                mixed_ms,
                palette_ms,
                colour_ms: total_ms - sampling_ms,
                total_ms,
            },
        })
    }
}
/// Equal-channel, zero-mean eight-phase noise: <= .4375 of one code, never lift black.
pub fn quantize(rgb: [f32; 3], dither: bool, frame: usize, zone: usize) -> [u8; 3] {
    if rgb == [0.0; 3] {
        return [0; 3];
    }
    let phase = (frame + zone * 3) % 8;
    let noise = if dither {
        (phase as f32 + 0.5) / 8.0 - 0.5
    } else {
        0.0
    };
    rgb.map(|x| {
        if x <= 0.0 {
            0
        } else {
            (x + noise).round_ties_even().clamp(0.0, 255.0) as u8
        }
    })
}
