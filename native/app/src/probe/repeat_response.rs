//! Actual HID response to a generated source event; no monitor/optical claim.
use super::levels::{guarded, Device};
use crate::{config::Store, pipeline::quantize_acknowledged, repeat::Repeat};
use anyhow::{ensure, Context, Result};
use std::{
    sync::mpsc,
    time::{Duration, Instant},
};

const OFFSETS: [u64; 4] = [101, 137, 251, 263];
pub fn plan(store: &Store) -> Result<serde_json::Value> {
    ensure!(
        (1..=512).contains(&store.config.device_zone_count),
        "Manual zone count required"
    );
    Ok(serde_json::json!({
        "scope":"Generated neutral source-event to final actual HID write; saturated serial repeat baseline vs guarded repeat suppression; no capture, optical timing or config writes",
        "manual_zones":store.config.device_zone_count,"requested_brightness":10,
        "raw_codes":[8,64],"fractional_control":"Only zone 0 starts at 8.25; must keep all dither phases",
        "source_offsets_ms":OFFSETS,"order_per_offset":["baseline","suppression","suppression","baseline"],
        "trials":32,"duration_limit_seconds":20,"default":"Plan only; --repeat-response --run required",
        "timing_limits":"Generated event is available independently of blocking USB. This excludes capture/panel/optical latency and is not daily-use FPS or power evidence.",
    }))
}

fn trial(
    device: &mut impl Device,
    count: usize,
    enabled: bool,
    fractional: bool,
    offset: u64,
) -> Result<serde_json::Value> {
    let mut raw = vec![[8.0; 3]; count];
    if fractional {
        raw[0] = [8.25; 3];
    }
    let mut acknowledged = 0;
    let colors = quantize_acknowledged(&raw, acknowledged);
    device.frame(&colors)?;
    acknowledged += 1;
    let mut repeat = Repeat::default();
    repeat.acknowledged(&colors, Instant::now());
    let mut repeats = 0;
    let mut suppressed = 0;
    std::thread::scope(|scope| -> Result<_> {
        let (tx, rx) = mpsc::sync_channel(1);
        scope.spawn(move || {
            std::thread::sleep(Duration::from_millis(offset));
            let _ = tx.send(Instant::now());
        });
        let event = loop {
            if let Ok(at) = rx.try_recv() {
                break at;
            }
            let colors = quantize_acknowledged(&raw, acknowledged);
            if enabled && repeat.can_suppress(&colors, Some(&raw), true, Instant::now()) {
                suppressed += 1;
                match rx.recv_timeout(repeat.refresh_delay(Instant::now()).unwrap_or_default()) {
                    Ok(at) => break at,
                    Err(mpsc::RecvTimeoutError::Timeout) => continue,
                    Err(error) => return Err(error.into()),
                }
            } else {
                device.frame(&colors)?;
                acknowledged += 1;
                repeats += 1;
                repeat.acknowledged(&colors, Instant::now());
            }
        };
        let changed = vec![[64.0; 3]; count];
        let colors = quantize_acknowledged(&changed, acknowledged);
        let timing = device.frame(&colors)?;
        let written = timing
            .write_completed
            .context("No final HID write timestamp")?;
        ensure!(written >= event, "Invalid source/write clock order");
        Ok(
            serde_json::json!({"suppression":enabled,"fractional_control":fractional,"source_offset_ms":offset,
            "repeated_transactions":repeats,"suppressed_checks":suppressed,
            "source_event_to_write_ms":written.duration_since(event).as_secs_f64()*1000.0,
            "source_event_to_ack_ms":event.elapsed().as_secs_f64()*1000.0,
            "changed_transaction":timing}),
        )
    })
}
fn measure(device: &mut impl Device, count: usize) -> Result<Vec<serde_json::Value>> {
    let start = Instant::now();
    let mut trials = Vec::new();
    for fractional in [false, true] {
        for offset in OFFSETS {
            for enabled in [false, true, true, false] {
                ensure!(
                    start.elapsed() < Duration::from_secs(20),
                    "Repeat response duration limit reached"
                );
                let brightness = device.query(0x08, &[])?;
                ensure!(
                    brightness.len() == 1 && brightness[0] <= 100,
                    "Invalid brightness readback"
                );
                let mut result = trial(device, count, enabled, fractional, offset)?;
                result["controller_brightness_readback"] = brightness[0].into();
                trials.push(result);
            }
        }
    }
    Ok(trials)
}
pub fn run(store: &Store) -> Result<()> {
    let description = plan(store)?;
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    let outcome = guarded(&mut strip, c.device_zone_count, Some(10), |d| {
        measure(d, c.device_zone_count)
    });
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Response trial or restoration failed"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::device::TransactionTimes;
    struct Fake {
        timestamp: bool,
    }
    impl Device for Fake {
        fn query(&mut self, _: u8, _: &[u8]) -> Result<Vec<u8>> {
            unreachable!()
        }
        fn frame(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
            assert_eq!(colors.len(), 48);
            assert!(colors
                .iter()
                .all(|p| p[0] == p[1] && p[1] == p[2] && [8, 9, 64].contains(&p[0])));
            std::thread::sleep(Duration::from_millis(1));
            Ok(TransactionTimes {
                write_completed: self.timestamp.then(Instant::now),
                ..Default::default()
            })
        }
        fn restore(&mut self, _: &[u8], _: &[u8]) -> bool {
            unreachable!()
        }
    }
    #[test]
    fn source_is_independent_of_actor_wait_and_missing_write_clock_is_rejected() {
        let result = trial(&mut Fake { timestamp: true }, 48, true, false, 3).unwrap();
        assert_eq!(result["repeated_transactions"], 0);
        assert!(result["suppressed_checks"].as_u64().unwrap() > 0);
        assert!(result["source_event_to_write_ms"].as_f64().unwrap() >= 0.0);
        assert!(trial(&mut Fake { timestamp: false }, 48, true, false, 3).is_err());
        let result = trial(&mut Fake { timestamp: true }, 48, true, true, 3).unwrap();
        assert_eq!(result["suppressed_checks"], 0);
    }
}
