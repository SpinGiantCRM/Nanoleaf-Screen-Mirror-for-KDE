//! Operator experiment: suppress only phase-invariant, already acknowledged bytes.
//! No synthetic ACK, dither-phase advance, inferred packet or unbounded idle hold.
use std::time::{Duration, Instant};

const REFRESH: Duration = Duration::from_millis(250);

#[derive(Default)]
pub struct Repeat {
    last: Vec<[u8; 3]>,
    at: Option<Instant>,
}
impl Repeat {
    pub fn refresh_delay(&self, now: Instant) -> Option<Duration> {
        self.at
            .map(|at| REFRESH.saturating_sub(now.saturating_duration_since(at)))
    }
    pub fn reset(&mut self) {
        self.last.clear();
        self.at = None;
    }
    pub fn acknowledged(&mut self, colors: &[[u8; 3]], now: Instant) {
        self.last.clear();
        self.last.extend_from_slice(colors);
        self.at = Some(now);
    }
    pub fn can_suppress(
        &self,
        colors: &[[u8; 3]],
        raw: Option<&[[f32; 3]]>,
        dither: bool,
        now: Instant,
    ) -> bool {
        if colors.is_empty()
            || colors != self.last
            || self
                .at
                .is_none_or(|at| now.saturating_duration_since(at) >= REFRESH)
        {
            return false;
        }
        if !dither {
            return true;
        }
        let Some(raw) =
            raw.filter(|v| v.len() == colors.len() && v.iter().flatten().all(|x| x.is_finite()))
        else {
            return false;
        };
        // Looking only at the next encoded frame can strand a fractional target
        // on an unchanged phase forever. Prove all eight phases are identical.
        raw.iter()
            .enumerate()
            .zip(colors)
            .all(|((zone, &rgb), &expected)| {
                (0..8).all(|phase| crate::pipeline::quantize(rgb, true, phase, zone) == expected)
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipeline::quantize_acknowledged;
    #[test]
    fn partial_fractional_zone_cannot_freeze_on_an_identical_next_phase() {
        let mut raw = vec![[64.0; 3]; 48];
        raw[0] = [64.25; 3];
        let first = quantize_acknowledged(&raw, 0);
        assert_eq!(first, quantize_acknowledged(&raw, 1));
        assert_ne!(first, quantize_acknowledged(&raw, 6));
        let now = Instant::now();
        let mut repeat = Repeat::default();
        repeat.acknowledged(&first, now);
        for phase in 0..8 {
            assert!(!repeat.can_suppress(
                &quantize_acknowledged(&raw, phase),
                Some(&raw),
                true,
                now
            ));
        }
        // Over a full cycle the fractional zone must reach the existing 64.25
        // average. Blind next-phase deduplication would hold it at 64 forever.
        let average = (0..8)
            .map(|p| f32::from(quantize_acknowledged(&raw, p)[0][0]))
            .sum::<f32>()
            / 8.0;
        assert_eq!(average, 64.25);
    }
    #[test]
    fn every_integer_neutral_is_exact_but_refresh_first_frame_and_reset_still_send() {
        let now = Instant::now();
        for code in 0..=255 {
            let colors = vec![[code; 3]; 48];
            let raw = vec![[f32::from(code); 3]; 48];
            let mut repeat = Repeat::default();
            assert!(!repeat.can_suppress(&colors, Some(&raw), true, now));
            repeat.acknowledged(&colors, now);
            assert!(repeat.can_suppress(
                &colors,
                Some(&raw),
                true,
                now + Duration::from_millis(249)
            ));
            assert!(!repeat.can_suppress(&colors, Some(&raw), true, now + REFRESH));
            repeat.reset();
            assert!(!repeat.can_suppress(&colors, Some(&raw), true, now));
        }
    }
    #[test]
    fn changed_bytes_unknown_precision_and_invalid_shapes_force_real_transactions() {
        let now = Instant::now();
        let mut repeat = Repeat::default();
        repeat.acknowledged(&[[20; 3]], now);
        assert!(!repeat.can_suppress(&[[21; 3]], None, false, now));
        assert!(!repeat.can_suppress(&[[20; 3]], None, true, now));
        assert!(!repeat.can_suppress(&[[20; 3]], Some(&[]), true, now));
        assert!(!repeat.can_suppress(&[[20; 3]], Some(&[[f32::NAN; 3]]), true, now));
        assert!(repeat.can_suppress(&[[20; 3]], None, false, now));
    }
}
