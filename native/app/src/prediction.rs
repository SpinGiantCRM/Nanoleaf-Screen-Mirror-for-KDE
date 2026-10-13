//! Optional perceived-cadence polish. Never feeds inferred colours back into
//! observed history. Accuracy/reference modes bypass this module completely.
use crate::config::Config;
use std::time::{Duration, Instant};

pub fn enabled(c: &Config) -> bool {
    c.sync_mode == "4d"
        && c.predictive_sync_strength > 0.0
        && !c.accuracy_mode
        && !matches!(c.color_style.as_str(), "reference" | "natural")
        && !c.blue_noise_dither
}

#[derive(Default)]
pub struct Predictor {
    previous: Vec<[u8; 3]>,
    current: Vec<[u8; 3]>,
    delta: Vec<[i16; 3]>,
    at: Option<Instant>,
    interval: Duration,
    stable: bool,
    emitted: bool,
}
impl Predictor {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn observe(&mut self, colors: &[[u8; 3]], at: Instant) {
        let interval = self.at.and_then(|old| at.checked_duration_since(old));
        let valid = interval.is_some_and(|d| {
            (Duration::from_millis(8)..=Duration::from_millis(80)).contains(&d)
                && (self.interval.is_zero()
                    || (d.as_secs_f64() / self.interval.as_secs_f64() - 1.0).abs() < 0.35)
        }) && colors.len() == self.current.len();
        let delta: Vec<[i16; 3]> = colors
            .iter()
            .zip(&self.current)
            .map(|(a, b)| std::array::from_fn(|k| i16::from(a[k]) - i16::from(b[k])))
            .collect();
        // Three observations, steady direction, no cuts or rapid colour changes.
        self.stable = valid
            && delta.len() == self.delta.len()
            && !delta.is_empty()
            && delta
                .iter()
                .zip(&self.delta)
                .all(|(a, b)| (0..3).all(|k| a[k].abs() <= 12 && (a[k] - b[k]).abs() <= 2));
        self.previous = std::mem::replace(&mut self.current, colors.to_vec());
        self.delta = delta;
        self.at = Some(at);
        self.interval = interval.unwrap_or_default();
        self.emitted = false;
    }
    pub fn deadline(&self, c: &Config) -> Option<Instant> {
        (enabled(c) && self.stable && !self.emitted)
            .then(|| {
                self.at
                    .map(|at| at + Duration::from_secs_f64(1.0 / c.fps as f64))
            })
            .flatten()
    }
    pub fn predict(&mut self, c: &Config, now: Instant) -> Option<Vec<[u8; 3]>> {
        self.predict_with_budget(c, now, Duration::ZERO)
    }
    /// Leave enough bus time for both the inference ACK and the next measured
    /// source packet. Prefer fresh source latency over an extra synthetic write.
    pub fn predict_with_budget(
        &mut self,
        c: &Config,
        now: Instant,
        usb: Duration,
    ) -> Option<Vec<[u8; 3]>> {
        if now < self.deadline(c)? {
            return None;
        }
        self.emitted = true; // At most one inferred packet per observed frame.
        let age = now.checked_duration_since(self.at?)?;
        if age + usb.saturating_mul(2) + Duration::from_millis(2) >= self.interval
            || age > self.interval + Duration::from_millis(12)
            || age > Duration::from_millis(100)
            || age < Duration::from_secs_f64(1.0 / c.fps as f64)
        {
            return None;
        }
        let ratio = (age.as_secs_f64() / self.interval.as_secs_f64() * c.predictive_sync_strength)
            .min(0.25);
        let mut out = self.current.clone();
        for ((rgb, old), step) in out.iter_mut().zip(&self.previous).zip(&self.delta) {
            let peak = *rgb.iter().max().unwrap();
            // Preserve black, low light, dimming and neutrals. Never invent a
            // previously absent channel or alter a fractional dither duty cycle.
            if peak < 40 || (0..3).any(|k| rgb[k] < old[k]) {
                continue;
            }
            let neutral = rgb[0] == rgb[1] && rgb[1] == rgb[2];
            if neutral && !(old[0] == old[1] && old[1] == old[2]) {
                continue;
            }
            for k in 0..3 {
                if rgb[k] > 0 {
                    let extra = (f64::from(step[k]) * ratio)
                        .round_ties_even()
                        .clamp(-1.0, 1.0);
                    rgb[k] = (f64::from(rgb[k]) + extra).clamp(0.0, 255.0) as u8;
                }
            }
        }
        (out != self.current).then_some(out)
    }
}
