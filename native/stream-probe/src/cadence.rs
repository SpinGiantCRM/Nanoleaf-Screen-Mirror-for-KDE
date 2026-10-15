//! Wake for the remaining unchanged-source interval, not a new full period.
use anyhow::{Context, Result};
use std::time::{Duration, Instant};

pub fn remaining(last: Option<Instant>, period: Duration, now: Instant) -> Option<Duration> {
    Some(period.saturating_sub(now.checked_duration_since(last?)?))
}

/// Loop::iterate floors finite timeouts to milliseconds. A one-shot SPA timer
/// retains nanosecond deadlines without a sub-millisecond polling spin. Keep a
/// bounded outer wait for permission/cancellation checks even at low target FPS.
pub fn arm(
    timer: &pipewire::loop_::TimerSource<'_>,
    delay: Option<Duration>,
) -> Result<pipewire::loop_::Timeout> {
    let due = delay.is_some_and(|d| d.is_zero());
    // SPA interprets a zero timer value as disarmed, not "fire immediately".
    timer
        .update_timer(delay.filter(|d| !d.is_zero()), None)
        .into_result()
        .context("Schedule unchanged-source update")?;
    Ok(if due {
        pipewire::loop_::Timeout::None
    } else {
        pipewire::loop_::Timeout::Finite(Duration::from_millis(100))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn remaining_interval_does_not_restart_after_an_early_wake() {
        let start = Instant::now();
        let period = Duration::from_secs_f64(1.0 / 60.0);
        let early = start + Duration::from_millis(16);
        assert_eq!(
            i32::try_from(pipewire::loop_::Timeout::Finite(period)).unwrap(),
            16
        );
        assert_eq!(
            remaining(Some(start), period, early),
            Some(period - Duration::from_millis(16))
        );
        assert_eq!(
            remaining(Some(start), period, start + period),
            Some(Duration::ZERO)
        );
        assert_eq!(
            remaining(Some(start), period, start + period * 100),
            Some(Duration::ZERO)
        );
        assert_eq!(remaining(None, period, start), None);
        assert_eq!(remaining(Some(early), period, start), None);
        // A fresh source resets the deadline; it is not held to the old phase.
        assert_eq!(remaining(Some(early), period, early), Some(period));
    }
}
