//! Full-length, serial transactions: distinguish active count from last position.
use super::levels::{guarded, Device};
use crate::config::Store;
use anyhow::{ensure, Result};
use std::time::{Duration, Instant};

const SAMPLES: usize = 16;

struct Pattern {
    name: &'static str,
    level: u8,
    indices: Vec<usize>,
}
fn patterns(count: usize) -> Result<Vec<Pattern>> {
    ensure!(
        (8..=512).contains(&count),
        "Position probe requires 8..512 manual zones"
    );
    let quarter = count / 4;
    let mut result = Vec::new();
    for level in [8, 64] {
        for (name, indices) in [
            ("black", vec![]),
            ("one-first", vec![0]),
            ("one-middle", vec![count / 2]),
            ("one-last", vec![count - 1]),
            ("quarter-first", (0..quarter).collect()),
            ("quarter-last", (count - quarter..count).collect()),
            (
                "quarter-spaced",
                (0..quarter)
                    .map(|i| i * (count - 1) / (quarter - 1))
                    .collect(),
            ),
            ("all", (0..count).collect()),
        ] {
            result.push(Pattern {
                name,
                level,
                indices,
            });
        }
    }
    Ok(result)
}
pub fn plan(store: &Store) -> Result<serde_json::Value> {
    let count = store.config.device_zone_count;
    let cases: Vec<_> = patterns(count)?
        .iter()
        .map(|p| {
            serde_json::json!({
                "pattern":p.name,"raw_neutral_code":p.level,"active_zone_indices":p.indices,
                "active_zones":p.indices.len(),"last_active_index":p.indices.last(),
            })
        })
        .collect();
    Ok(serde_json::json!({
        "scope":"Generated full-length neutral frames; no capture, short payloads, firmware or config writes",
        "manual_zones":count,"cases_forward":cases,"passes":"forward then reverse",
        "samples_per_case":SAMPLES,"warmup_samples_per_case":2,
        "test_transactions":cases.len()*SAMPLES*2,"duration_limit_seconds":25,
        "requested_controller_brightness":10,"effective_brightness":"Not assumed; readback recorded per case",
        "requires":"--positions --run; otherwise plan only",
        "restoration":"Existing black cleanup and original power/brightness readback; prior colours cannot be read back",
        "optical_measurement":false,
    }))
}
fn measure(device: &mut impl Device, count: usize) -> Result<Vec<serde_json::Value>> {
    let cases = patterns(count)?;
    let start = Instant::now();
    let mut output = Vec::new();
    for reverse in [false, true] {
        for j in 0..cases.len() {
            let p = &cases[if reverse { cases.len() - 1 - j } else { j }];
            ensure!(
                start.elapsed() < Duration::from_secs(25),
                "Position probe duration limit reached"
            );
            let brightness = device.query(0x08, &[])?;
            ensure!(
                brightness.len() == 1 && brightness[0] <= 100,
                "Invalid brightness readback"
            );
            let mut frame = vec![[0; 3]; count];
            for &i in &p.indices {
                frame[i] = [p.level; 3];
            }
            let mut samples = Vec::with_capacity(SAMPLES);
            for _ in 0..SAMPLES {
                ensure!(
                    start.elapsed() < Duration::from_secs(25),
                    "Position probe duration limit reached"
                );
                samples.push(device.frame(&frame)?);
            }
            output.push(
                serde_json::json!({"pattern":p.name,"raw_neutral_code":p.level,
                "active_zone_indices":p.indices,"active_zones":p.indices.len(),
                "last_active_index":p.indices.last(),"reverse_pass":reverse,
                "controller_brightness_readback":brightness[0],"samples":samples}),
            );
        }
    }
    Ok(output)
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
    let result = guarded(&mut strip, c.device_zone_count, Some(10), |d| {
        measure(d, c.device_zone_count)
    });
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":result})
    );
    ensure!(
        result["error"].is_null()
            && result["black_cleanup_acknowledged"] == true
            && result["controller_restored"] == true,
        "Position test or controller restoration failed"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::device::TransactionTimes;
    #[test]
    fn count_and_extent_are_independent_and_every_frame_is_complete() {
        for n in [8, 47, 48, 75, 512] {
            let cases = patterns(n).unwrap();
            assert_eq!(cases.len(), 16);
            for p in &cases {
                let mut unique = p.indices.clone();
                unique.sort();
                unique.dedup();
                assert_eq!(unique, p.indices);
                assert!(p.indices.iter().all(|i| *i < n));
            }
            assert_eq!(cases[1].indices.len(), cases[3].indices.len());
            assert_eq!(cases[3].indices, vec![n - 1]);
            assert_eq!(cases[4].indices.len(), cases[5].indices.len());
            assert_eq!(cases[5].indices.len(), cases[6].indices.len());
            assert_eq!(cases[6].indices.last(), Some(&(n - 1)));
        }
        for n in [0, 1, 7, 513] {
            assert!(patterns(n).is_err());
        }
    }
    #[test]
    fn generated_trial_retains_both_orders_and_all_samples_without_changing_geometry() {
        struct Fake {
            frames: usize,
        }
        impl Device for Fake {
            fn query(&mut self, command: u8, payload: &[u8]) -> Result<Vec<u8>> {
                assert_eq!(command, 0x08);
                assert!(payload.is_empty());
                Ok(vec![16])
            }
            fn frame(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
                assert_eq!(colors.len(), 48);
                assert!(colors
                    .iter()
                    .all(|p| [0, 8, 64].contains(&p[0]) && p[0] == p[1] && p[1] == p[2]));
                self.frames += 1;
                Ok(TransactionTimes::default())
            }
            fn restore(&mut self, _: &[u8], _: &[u8]) -> bool {
                panic!("measurement cannot restore or mutate power")
            }
        }
        let mut fake = Fake { frames: 0 };
        let trials = measure(&mut fake, 48).unwrap();
        assert_eq!(fake.frames, 512);
        assert_eq!(trials.len(), 32);
        assert_eq!(trials[0]["pattern"], trials[31]["pattern"]);
        assert_eq!(trials[0]["reverse_pass"], false);
        assert_eq!(trials[31]["reverse_pass"], true);
        assert!(trials
            .iter()
            .all(|r| r["controller_brightness_readback"] == 16
                && r["samples"].as_array().unwrap().len() == 16));
    }
}
