//! Operator-only raw channel-level comparison. No calibration or config writes.
use crate::{config::Store, device::TransactionTimes};
use anyhow::{ensure, Context, Result};
use std::time::{Duration, Instant};

const LEVELS: [u8; 9] = [0, 15, 16, 24, 0, 24, 16, 15, 0];
const PHASE_SECONDS: u64 = 2;
const SINGLE_SECONDS: u64 = 10;
const TEST_BRIGHTNESS: u8 = 10;

pub fn plan(store: &Store) -> Result<serde_json::Value> {
    let count = store.config.device_zone_count;
    ensure!((1..=512).contains(&count), "Manual zone count required");
    Ok(serde_json::json!({
        "scope": "Raw generated neutral drive codes; no screen capture or calibration changes",
        "manual_zones": count,
        "raw_levels": LEVELS,
        "seconds_per_phase": PHASE_SECONDS,
        "nominal_seconds": LEVELS.len() as u64 * PHASE_SECONDS,
        "maximum_raw_channel": 24,
        "brightness_policy": "No test brightness setting; raw code cap does not assert optical brightness",
        "hardware_run_requires": "--run; default prints this plan without opening HID",
        "restoration": "Black cleanup, then original controller power/brightness with readback; prior LED colours cannot be read back",
        "optical_measurement": false,
    }))
}

/// One individually labelled observation avoids interpreting a fast sequence.
pub fn single_plan(store: &Store, level: u8) -> Result<serde_json::Value> {
    ensure!(
        [0, 15, 16, 24].contains(&level),
        "Use raw code 0, 15, 16 or 24"
    );
    let mut out = plan(store)?;
    out["raw_levels"] = serde_json::json!([level]);
    out["seconds_per_phase"] = SINGLE_SECONDS.into();
    out["nominal_seconds"] = SINGLE_SECONDS.into();
    out["brightness_policy"] = "Set controller brightness to 10 during this single observation; restore original power/brightness with readback. Raw codes are not optical brightness measurements.".into();
    out["test_controller_brightness"] = TEST_BRIGHTNESS.into();
    Ok(out)
}

trait Device {
    fn query(&mut self, command: u8, payload: &[u8]) -> Result<Vec<u8>>;
    fn frame(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes>;
    fn restore(&mut self, power: &[u8], brightness: &[u8]) -> bool;
}
impl Device for crate::device::Strip {
    fn query(&mut self, command: u8, payload: &[u8]) -> Result<Vec<u8>> {
        self.request(command, payload)
    }
    fn frame(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
        crate::device::Strip::frame(self, colors)?;
        self.last_frame_transaction
            .clone()
            .context("Missing acknowledged timing")
    }
    fn restore(&mut self, power: &[u8], brightness: &[u8]) -> bool {
        self.restore_controller(power, brightness)
    }
}

/// Returned errors still run cleanup and restoration. Physical unplug/process
/// termination can prevent restoration; never claim success without readback.
fn guarded<D: Device>(
    device: &mut D,
    count: usize,
    test_brightness: Option<u8>,
    work: impl FnOnce(&mut D) -> Result<Vec<serde_json::Value>>,
) -> serde_json::Value {
    let snapshot = (|| -> Result<_> {
        let power = device.query(0x06, &[])?;
        let brightness = device.query(0x08, &[])?;
        ensure!(
            power.len() == 1 && power[0] <= 1 && brightness.len() == 1,
            "Invalid controller state; no output started"
        );
        Ok((power, brightness))
    })();
    let (power, brightness) = match snapshot {
        Ok(values) => values,
        Err(error) => return serde_json::json!({"error":error.to_string(),"output_started":false}),
    };
    let black = vec![[0; 3]; count];
    let result = (|| -> Result<_> {
        if let Some(brightness) = test_brightness {
            device.query(0x09, &[brightness])?;
        }
        device.frame(&black)?;
        device.query(0x07, &[1])?;
        work(device)
    })();
    let black_ok = device.frame(&black).is_ok();
    let restored = device.restore(&power, &brightness);
    serde_json::json!({
        "output_started": true,
        "original_controller_power": power[0],
        "original_controller_brightness": brightness[0],
        "phases": result.as_ref().ok(),
        "error": result.as_ref().err().map(ToString::to_string),
        "black_cleanup_acknowledged": black_ok,
        "controller_restored": restored,
    })
}

pub fn run(store: &Store) -> Result<()> {
    run_sequence(store, &LEVELS, PHASE_SECONDS, None, plan(store)?)
}
pub fn run_single(store: &Store, level: u8) -> Result<()> {
    run_sequence(
        store,
        &[level],
        SINGLE_SECONDS,
        Some(TEST_BRIGHTNESS),
        single_plan(store, level)?,
    )
}
fn run_sequence(
    store: &Store,
    levels: &[u8],
    seconds: u64,
    brightness: Option<u8>,
    description: serde_json::Value,
) -> Result<()> {
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let config = &store.config;
    let mut device = crate::device::Strip::open(
        config.device_vid,
        config.device_pid,
        config.device_zone_count,
        &config.output_channel_order,
    )?;
    let outcome = guarded(
        &mut device,
        config.device_zone_count,
        brightness,
        |device| {
            let mut phases = Vec::new();
            for (phase, &level) in levels.iter().enumerate() {
                eprintln!(
                    "Phase {}/{}: raw neutral code {level}",
                    phase + 1,
                    levels.len()
                );
                let frame = vec![[level; 3]; config.device_zone_count];
                let started = Instant::now();
                let mut deadline = started;
                let mut samples = Vec::new();
                while started.elapsed() < Duration::from_secs(seconds) {
                    std::thread::sleep(deadline.saturating_duration_since(Instant::now()));
                    if started.elapsed() >= Duration::from_secs(seconds) {
                        break;
                    }
                    samples.push(Device::frame(device, &frame)?);
                    deadline = (deadline + Duration::from_nanos(33_333_333)).max(Instant::now());
                }
                phases.push(serde_json::json!({
                    "phase":phase + 1,"raw_neutral_code":level,
                    "elapsed_seconds":started.elapsed().as_secs_f64(),"transactions":samples,
                }));
            }
            Ok(phases)
        },
    );
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Level comparison or controller restoration failed"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[derive(Default)]
    struct Fake {
        frames: usize,
        restore_calls: usize,
        fail_initial_black: bool,
        malformed_power: bool,
        fail_cleanup: bool,
        fail_restore: bool,
        fail_power_on: bool,
        fail_test_brightness: bool,
        brightness_calls: usize,
    }
    impl Device for Fake {
        fn query(&mut self, command: u8, payload: &[u8]) -> Result<Vec<u8>> {
            if command == 0x09 {
                self.brightness_calls += 1;
                assert_eq!(payload, &[TEST_BRIGHTNESS]);
                ensure!(!self.fail_test_brightness, "Injected brightness failure");
                return Ok(vec![]);
            }
            ensure!(
                !(self.fail_power_on && command == 0x07),
                "Injected power error"
            );
            Ok(match command {
                0x06 if self.malformed_power => vec![2],
                0x06 => vec![0],
                0x08 => vec![137],
                0x07 => vec![],
                _ => panic!("Unexpected command"),
            })
        }
        fn frame(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
            self.frames += 1;
            assert_eq!(colors, &[[0; 3]; 48]);
            ensure!(
                !(self.fail_initial_black && self.frames == 1
                    || self.fail_cleanup && self.frames == 2),
                "Injected output failure"
            );
            Ok(TransactionTimes::default())
        }
        fn restore(&mut self, power: &[u8], brightness: &[u8]) -> bool {
            assert_eq!(power, &[0]);
            assert_eq!(brightness, &[137]);
            self.restore_calls += 1;
            !self.fail_restore
        }
    }
    #[test]
    fn failed_experiment_still_cleans_output_and_restores_original_state() {
        let mut device = Fake::default();
        let out = guarded(&mut device, 48, None, |_| {
            anyhow::bail!("Injected phase failure")
        });
        assert_eq!(device.frames, 2);
        assert_eq!(device.restore_calls, 1);
        assert_eq!(out["controller_restored"], true);
        assert_eq!(out["error"], "Injected phase failure");
    }
    #[test]
    fn failed_initial_or_cleanup_frame_does_not_skip_restoration() {
        for initial in [false, true] {
            let mut device = Fake {
                fail_initial_black: initial,
                fail_cleanup: !initial,
                ..Fake::default()
            };
            let out = guarded(&mut device, 48, None, |_| Ok(vec![]));
            assert_eq!(device.restore_calls, 1);
            assert_eq!(out["controller_restored"], true);
            assert!(out["error"].is_string() || out["black_cleanup_acknowledged"] == false);
        }
        let mut device = Fake {
            fail_power_on: true,
            ..Fake::default()
        };
        let out = guarded(&mut device, 48, None, |_| panic!("Power-on failed"));
        assert_eq!(device.restore_calls, 1);
        assert_eq!(device.frames, 2);
        assert_eq!(out["error"], "Injected power error");
    }
    #[test]
    fn malformed_snapshot_prevents_any_output_and_failed_restore_is_reported() {
        let mut device = Fake {
            malformed_power: true,
            ..Fake::default()
        };
        let out = guarded(&mut device, 48, None, |_| panic!("Must not run"));
        assert_eq!(device.frames, 0);
        assert_eq!(device.restore_calls, 0);
        assert_eq!(out["output_started"], false);
        let mut device = Fake {
            fail_restore: true,
            ..Fake::default()
        };
        let out = guarded(&mut device, 48, None, |_| Ok(vec![]));
        assert_eq!(out["controller_restored"], false);
    }
    #[test]
    fn successful_probe_preserves_snapshot_and_reports_cleanup() {
        let mut device = Fake::default();
        let out = guarded(&mut device, 48, None, |_| Ok(vec![]));
        assert!(out["error"].is_null());
        assert_eq!(out["original_controller_power"], 0);
        assert_eq!(out["original_controller_brightness"], 137);
        assert_eq!(out["black_cleanup_acknowledged"], true);
        assert_eq!(out["controller_restored"], true);
        assert_eq!(device.restore_calls, 1);
    }
    #[test]
    fn single_observation_restores_snapshot_even_when_brightness_or_work_fails() {
        for fail in [false, true] {
            let mut device = Fake {
                fail_test_brightness: fail,
                ..Fake::default()
            };
            let mut ran = false;
            let out = guarded(&mut device, 48, Some(TEST_BRIGHTNESS), |_| {
                ran = true;
                anyhow::bail!("Injected observation failure")
            });
            assert_eq!(ran, !fail);
            assert_eq!(device.brightness_calls, 1);
            assert_eq!(device.restore_calls, 1);
            assert_eq!(out["original_controller_brightness"], 137);
            assert_eq!(out["black_cleanup_acknowledged"], true);
            assert_eq!(out["controller_restored"], true);
        }
    }
}
