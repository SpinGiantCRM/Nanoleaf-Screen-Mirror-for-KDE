//! Stateful single-strip processing. Capture pixels carry an explicit SDR contract.
use crate::{capture::Frame, config::Config, geometry};
use anyhow::{ensure, Context, Result};
use nanoleaf_core::{
    adaptive::MixedDecision,
    blending::BlendState,
    colour::{self, LedCalibration, Style},
    palette::{self, Algorithm, TemporalState},
    sampling::{SdrRgb8Frame, SdrSampler, ZoneRect, ZoneSample},
};
use serde::Serialize;
use std::time::Instant;

#[derive(Default, Clone, Debug, Serialize, serde::Deserialize)]
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
    highlight: crate::highlight::Cache,
    disable_highlight_cache: bool,
    legacy_black_hold_oracle: bool,
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
    pub unquantized_rgb: Vec<[f32; 3]>,
    pub colors: Vec<[u8; 3]>,
    pub sampled: Vec<[u8; 3]>,
    pub modes: Vec<String>,
    pub times: ProcessingTimes,
    pub highlight_cache: (usize, u64),
}
struct PreparedSamples {
    raw: Vec<[u8; 3]>,
    modes: Vec<String>,
    mapping: Vec<usize>,
    mixed_ms: f64,
    palette_ms: f64,
    started: Instant,
}
/// The capture provider must preserve these exact configured rectangles. No
/// LED count or calibration is inferred from capture or controller metadata.
pub struct DirectPlan {
    pub zones: Vec<ZoneRect>,
    mapping: Vec<usize>,
    mode: &'static str,
}
/// Plan full-pixel box sampling only where no pixel-dependent policy is lost.
/// A backend must keep CPU capture/processing for unsupported policies.
pub fn direct_plan(c: &Config, width: usize, height: usize) -> Result<DirectPlan> {
    direct_plan_with_bounds(c, width, height, None)
}
pub fn direct_plan_with_bounds(
    c: &Config,
    width: usize,
    height: usize,
    bounds: Option<ContentBounds>,
) -> Result<DirectPlan> {
    validate_mirroring(c)?;
    ensure!(
        width > 0 && height > 0 && width <= 16384 && height <= 16384,
        "Invalid direct frame dimensions"
    );
    let accuracy = c.accuracy_mode || matches!(c.color_style.as_str(), "reference" | "natural");
    ensure!(
        accuracy
            || (matches!(c.sampling_mode.as_str(), "edge_direct" | "area_average")
                && !c.multi_moment_zone_colors),
        "Adaptive sampling requires the pixel path"
    );
    ensure!(
        c.zone_box_filter_sampling && (!c.letterbox_detection || bounds.is_some()) && c.privacy_zones.is_empty(),
        "Weighted/privacy policies require pixels; letterbox sampling requires verified content bounds"
    );
    let (mut zones, counts) = geometry::pixel_zones(c, width, height)?;
    if c.letterbox_detection {
        let bounds = bounds.context("Missing content bounds")?;
        bounds.validate(width, height)?;
        remap_content_bounds(width, height, bounds, &mut zones);
    }
    let mapping = geometry::calibrated_mapping(c, zones.len(), counts)?;
    let zones = zones
        .into_iter()
        .map(|z| anchor(z, width, height))
        .collect();
    Ok(DirectPlan {
        zones,
        mapping,
        mode: if accuracy || c.sampling_mode == "edge_direct" {
            "edge_direct"
        } else {
            "area_average"
        },
    })
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
    let bounds = detect_content_bounds(
        w,
        h,
        |y| Ok((0..w).map(|x| rgb(x, y)).sum::<f32>() / w as f32),
        |x, top, bottom| Ok((top..bottom).map(|y| rgb(x, y)).sum::<f32>() / (bottom - top) as f32),
    )
    .expect("Validated frame geometry");
    remap_content_bounds(w, h, bounds, zones)
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ContentBounds {
    pub left: usize,
    pub top: usize,
    pub right: usize,
    pub bottom: usize,
}
impl ContentBounds {
    pub fn validate(self, w: usize, h: usize) -> Result<()> {
        ensure!(
            self.left < self.right && self.top < self.bottom && self.right <= w && self.bottom <= h,
            "Invalid content bounds"
        );
        Ok(())
    }
}
/// Same float32 luma and ordered sum as the CPU frame detector. Providers return
/// full encoded RGB8 pixels, not a downscaled approximation.
pub fn encoded_mean(pixels: &[u8]) -> Result<f32> {
    ensure!(
        !pixels.is_empty() && pixels.len().is_multiple_of(3),
        "Invalid analysis pixels"
    );
    Ok(pixels
        .as_chunks::<3>()
        .0
        .iter()
        .map(|p| luma(p.map(f32::from)))
        .sum::<f32>()
        / (pixels.len() / 3) as f32)
}
pub fn detect_content_bounds(
    w: usize,
    h: usize,
    mut row: impl FnMut(usize) -> Result<f32>,
    mut col: impl FnMut(usize, usize, usize) -> Result<f32>,
) -> Result<ContentBounds> {
    ensure!(w > 0 && h > 0, "Empty content geometry");
    let mut top = 0;
    for y in (0..h).step_by(8) {
        if row(y)? > 4.0 {
            top = y;
            break;
        }
    }
    let mut bottom = h;
    for y in (top + 1..h).rev().step_by(8) {
        if row(y)? > 4.0 {
            bottom = y + 1;
            break;
        }
    }
    let mut left = 0;
    for x in (0..w).step_by(8) {
        if col(x, top, bottom)? > 4.0 {
            left = x;
            break;
        }
    }
    let mut right = w;
    for x in (left + 1..w).rev().step_by(8) {
        if col(x, top, bottom)? > 4.0 {
            right = x + 1;
            break;
        }
    }
    Ok(ContentBounds {
        left,
        top,
        right,
        bottom,
    })
}
fn remap_content_bounds(w: usize, h: usize, bounds: ContentBounds, zones: &mut [ZoneRect]) -> bool {
    let ContentBounds {
        left,
        top,
        right,
        bottom,
    } = bounds;
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
        c.capture_backend != "kmsgrab",
        "Native DRM capture awaits verification; use the working fallback"
    );
    let accuracy = c.accuracy_mode || matches!(c.color_style.as_str(), "reference" | "natural");
    ensure!(
        accuracy
            || matches!(
                c.sampling_mode.as_str(),
                "auto"
                    | "palette_adaptive"
                    | "edge_direct"
                    | "area_average"
                    | "peak_luma"
                    | "vivid_weighted"
                    | "wavelet"
            ),
        "Sampling mode {} awaits native verification; use the Python fallback",
        c.sampling_mode
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
    /// Old Python fixture arithmetic, including encoded-space accumulation,
    /// black-transition glow and ineffective chroma controls. Offline only.
    pub fn legacy_black_hold_oracle() -> Self {
        Self {
            legacy_black_hold_oracle: true,
            ..Default::default()
        }
    }

    /// Verification path; same arithmetic, with exact-patch reuse disabled.
    pub fn without_highlight_cache() -> Self {
        Self {
            disable_highlight_cache: true,
            ..Default::default()
        }
    }
    pub fn highlight_cache_statistics(&self) -> (usize, u64) {
        self.highlight.statistics()
    }
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
        if !accuracy && matches!(mode, "palette_adaptive" | "peak_luma" | "vivid_weighted") {
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
            matches!(
                mode,
                "palette_adaptive"
                    | "edge_direct"
                    | "area_average"
                    | "peak_luma"
                    | "vivid_weighted"
                    | "wavelet"
            ),
            "Sampling mode {mode} awaits native verification; use the Python fallback"
        );
        let masked = mask(frame, c);
        let bytes = masked.as_deref().unwrap_or(&frame.pixels);
        let view = SdrRgb8Frame::new(bytes, frame.width, frame.height, frame.width * 3)?;
        if self.palette.len() != zones.len() {
            self.palette = vec![TemporalState::default(); zones.len()];
        }
        let stride = if accuracy || c.virtual_zone_oversample > 0 {
            1
        } else {
            match c.sampling_quality.as_str() {
                "high" => 1,
                "low" => 4,
                _ => 2,
            }
        };
        if matches!(mode, "peak_luma" | "vivid_weighted") {
            self.highlight.reset(zones.len());
        } else {
            self.highlight.clear();
        }
        let mut mixed_ms = 0.0;
        let mut palette_ms = 0.0;
        let mut raw = Vec::with_capacity(zones.len());
        let mut modes = Vec::with_capacity(zones.len());
        for (index, z) in zones.into_iter().enumerate() {
            if matches!(mode, "edge_direct" | "area_average") && c.zone_box_filter_sampling {
                let z = if c.zone_box_filter_sampling {
                    anchor(z, frame.width, frame.height)
                } else {
                    z
                };
                if !accuracy && c.multi_moment_zone_colors {
                    let x = z.x.clamp(0, frame.width as i64) as usize;
                    let y = z.y.clamp(0, frame.height as i64) as usize;
                    let x1 = (z.x + z.width).clamp(x as i64, frame.width as i64) as usize;
                    let y1 = (z.y + z.height).clamp(y as i64, frame.height as i64) as usize;
                    let patch: Vec<_> = (y..y1)
                        .flat_map(|row| {
                            (x..x1).map(move |col| {
                                let i = (row * frame.width + col) * 3;
                                [bytes[i], bytes[i + 1], bytes[i + 2]]
                            })
                        })
                        .collect();
                    raw.push(crate::analysis::multi_moment(&self.sampler, &patch)?);
                    modes.push("multi_moment_actual_mean".to_string());
                } else {
                    raw.push(self.sampler.sample_zone(&view, z).srgb);
                    modes.push(mode.to_string());
                }
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
            if matches!(mode, "peak_luma" | "vivid_weighted") {
                let (color, fallback) = if self.disable_highlight_cache {
                    self.sampler.highlight_mean(&patch, mode == "peak_luma")?
                } else {
                    self.highlight
                        .sample(&self.sampler, index, patch, mode == "peak_luma")?
                };
                raw.push(color);
                modes.push(if fallback { "area_average" } else { mode }.to_string());
                continue;
            }
            if mode == "wavelet" {
                raw.push(crate::analysis::wavelet(
                    &self.sampler,
                    &patch,
                    (x1 - x).div_ceil(stride),
                )?);
                modes.push("wavelet_linear_detail".to_string());
                continue;
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
        self.finish(
            c,
            PreparedSamples {
                raw,
                modes,
                mapping,
                mixed_ms,
                palette_ms,
                started,
            },
        )
    }
    /// Consume validated SDR zone statistics through the SAME colour/mapping/
    /// temporal pipeline as CPU pixels. Caller establishes sRGB metadata first.
    pub fn process_sdr_samples(
        &mut self,
        width: usize,
        height: usize,
        samples: &[ZoneSample],
        c: &Config,
    ) -> Result<Output> {
        self.process_sdr_samples_with_bounds(width, height, samples, c, None)
    }
    pub fn process_sdr_samples_with_bounds(
        &mut self,
        width: usize,
        height: usize,
        samples: &[ZoneSample],
        c: &Config,
        bounds: Option<ContentBounds>,
    ) -> Result<Output> {
        let started = Instant::now();
        let plan = direct_plan_with_bounds(c, width, height, bounds)?;
        ensure!(
            samples.len() == plan.zones.len(),
            "Direct sample count differs from configured zones"
        );
        for (sample, zone) in samples.iter().zip(&plan.zones) {
            let x = zone.x.clamp(0, width as i64);
            let y = zone.y.clamp(0, height as i64);
            let w = zone.width.max(0).min(width as i64 - x) as u64;
            let h = zone.height.max(0).min(height as i64 - y) as u64;
            ensure!(
                sample.pixel_count == w * h && (sample.pixel_count != 0 || sample.srgb == [0; 3]),
                "Direct zone sample is incomplete"
            );
            ensure!(
                sample
                    .linear_rgb
                    .iter()
                    .all(|v| v.is_finite() && (0.0..=1.0).contains(v))
                    && sample.encoded_variance.is_finite()
                    && sample.encoded_variance >= 0.0,
                "Invalid SDR statistics"
            );
        }
        self.palette = vec![TemporalState::default(); samples.len()];
        self.finish(
            c,
            PreparedSamples {
                raw: samples.iter().map(|s| s.srgb).collect(),
                modes: vec![plan.mode.to_string(); samples.len()],
                mapping: plan.mapping,
                mixed_ms: 0.0,
                palette_ms: 0.0,
                started,
            },
        )
    }
    fn finish(&mut self, c: &Config, input: PreparedSamples) -> Result<Output> {
        let PreparedSamples {
            mut raw,
            modes,
            mapping,
            mixed_ms,
            palette_ms,
            started,
        } = input;
        let accuracy = c.accuracy_mode || matches!(c.color_style.as_str(), "reference" | "natural");
        let black: Vec<bool> = raw.iter().map(|rgb| *rgb == [0; 3]).collect();
        if c.zone_temporal_accumulation {
            if self.accumulation.len() != raw.len() {
                self.accumulation = raw
                    .iter()
                    .map(|v| {
                        v.map(|code| {
                            if self.legacy_black_hold_oracle {
                                f64::from(code)
                            } else {
                                f64::from(colour::decode_srgb(f32::from(code)))
                            }
                        })
                    })
                    .collect();
            } else {
                let a = 0.05 + 0.45 * (self.motion / 64.0).clamp(0.0, 1.0);
                for (acc, rgb) in self.accumulation.iter_mut().zip(&raw) {
                    if !self.legacy_black_hold_oracle && *rgb == [0; 3] {
                        *acc = [0.0; 3];
                        continue;
                    }
                    for k in 0..3 {
                        let current = if self.legacy_black_hold_oracle {
                            f64::from(rgb[k])
                        } else {
                            f64::from(colour::decode_srgb(f32::from(rgb[k])))
                        };
                        acc[k] = (1.0 - a) * acc[k] + a * current;
                    }
                }
            }
            raw = self
                .accumulation
                .iter()
                .map(|v| {
                    v.map(|x| {
                        let encoded = if self.legacy_black_hold_oracle {
                            x
                        } else {
                            f64::from(colour::encode_srgb(x as f32))
                        };
                        encoded.round_ties_even().clamp(0.0, 255.0) as u8
                    })
                })
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
        let mapped_black: Vec<_> = mapping.iter().map(|&i| black[i]).collect();
        let mut mapped: Vec<[f32; 3]> =
            mapping.into_iter().map(|i| raw[i].map(f32::from)).collect();
        if self.dark_hold.len() != mapped.len() {
            self.dark_hold = vec![false; mapped.len()];
        }
        for (i, rgb) in mapped.iter_mut().enumerate() {
            let y = luma(rgb.map(colour::decode_srgb));
            let held = if self.frame_index == 0 {
                y < c.led_calibration_profile_sdr.dark_sample_stabilize_on as f32
            } else if self.dark_hold[i] {
                y <= c.led_calibration_profile_sdr.dark_sample_stabilize_off as f32
            } else {
                y < c.led_calibration_profile_sdr.dark_sample_stabilize_on as f32
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
            *rgb = if self.legacy_black_hold_oracle {
                colour::apply_profile_legacy_oracle(*rgb, style, cal)
            } else {
                colour::apply_profile(*rgb, style, cal)
            }
            .map(f32::from);
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
        // Scene adaptation may improve response, but cannot override colour
        // style, calibration, capture FPS or the user's physical mapping.
        let (preset, minimum, speed) =
            if c.scene_adaptive_profiles && !accuracy && self.motion > 15.0 {
                ("responsive", minimum.max(0.8), speed.max(1.0))
            } else {
                (preset, minimum, speed)
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
        for (rgb, black) in mapped.iter_mut().zip(mapped_black) {
            if black && !self.legacy_black_hold_oracle {
                *rgb = [0.0; 3];
            }
        }
        self.previous_smooth = mapped.clone();
        if self.quant_hold.len() != mapped.len() {
            self.quant_hold = vec![false; mapped.len()];
        }
        // Holding an integer output before temporal quantization destroys its
        // fractional duty cycle. Use the legacy hold only when dither is off.
        // Inferred ACKs must not steer later measured source colours through
        // integer hold hysteresis. In opt-in prediction mode, quantize each
        // observed result directly; actual ACK history still records reality.
        if !c.blue_noise_dither
            && !crate::prediction::enabled(c)
            && self.previous_sent.len() == mapped.len()
        {
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
            unquantized_rgb: mapped,
            highlight_cache: self.highlight.statistics(),
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

/// Use acknowledged packet cadence for real output; dropped prepared frames
/// must not skip or repeat temporal dither phases on the physical strip.
pub fn quantize_acknowledged(rgb: &[[f32; 3]], acknowledged: u64) -> Vec<[u8; 3]> {
    rgb.iter()
        .enumerate()
        .map(|(i, &v)| quantize(v, true, (acknowledged % 8) as usize, i))
        .collect()
}
