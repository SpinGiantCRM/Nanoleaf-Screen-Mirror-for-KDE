//! Operator-only, serial short-prefix tests. Omitted-zone state is NOT inferred
//! from acknowledgements. The daily encoder still requires the full manual count.
use super::levels::{guarded, Device};
use crate::{config::Store, device::TransactionTimes};
use anyhow::{ensure, Result};
use std::time::{Duration, Instant};

const SAMPLES: usize = 12;
const OBSERVE_SECONDS: u64 = 30;

trait PrefixDevice: Device {
    fn prefix(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes>;
}
impl PrefixDevice for crate::device::Strip {
    fn prefix(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
        self.probe_prefix(colors)
    }
}

fn lengths(count: usize) -> Result<Vec<usize>> {
    ensure!(
        (8..=255).contains(&count),
        "Short probe requires 8..255 manual zones"
    );
    let mut lengths = vec![1, count / 4, 20, 21, count / 2, 41, 42, count - 1];
    lengths.retain(|n| *n > 0 && *n < count);
    lengths.sort_unstable();
    lengths.dedup();
    Ok(lengths)
}

fn observation(name: &str, count: usize) -> Result<([u8; 3], [u8; 3])> {
    lengths(count)?;
    Ok(match name {
        "red-prefix" => ([0, 0, 64], [64, 0, 0]),
        "black-prefix" => ([64, 0, 0], [0, 0, 0]),
        "green-prefix" => ([0, 0, 0], [0, 64, 0]),
        _ => anyhow::bail!("Use red-prefix, black-prefix or green-prefix"),
    })
}

pub fn plan(store: &Store, observe: Option<&str>) -> Result<serde_json::Value> {
    let count = store.config.device_zone_count;
    let lengths = lengths(count)?;
    let mut plan = serde_json::json!({
        "scope":"Operator-only valid nonempty RGB prefixes; no capture, calibration edits, firmware operations or daily transport change",
        "manual_zones":count,"requested_brightness":10,"raw_channel_cap":64,
        "requires":"--run; without it this is a hardware-free plan",
        "transport":"Existing serial command 0x02, exact TLV length, normal ACK for every command; no overlap/retry",
        "restoration":"Full manual-count black cleanup, original power/brightness and readback. Prior LED colours cannot be read back.",
        "optical_measurement":false,"omitted_zone_semantics":"Unknown until separately observed; ACK is not LED state readback",
    });
    if let Some(name) = observe {
        let (seed, prefix) = observation(name, count)?;
        plan["observation"] = serde_json::json!({
            "name":name,"seed_full_rgb":seed,"prefix_rgb":prefix,
            "prefix_zones":count/4,"omitted_zones":count-count/4,
            "seed_seconds":3,"observe_seconds":OBSERVE_SECONDS,"writes":"One full seed followed by ONE short command; no refresh while observing",
        });
    } else {
        plan["timing"] = serde_json::json!({
            "prefix_lengths":lengths,"levels":[8,64],"samples_per_case":SAMPLES,
            "warmup_samples_per_case":2,"orders":["full then short","short then full"],
            "precondition":"Full black before EACH measured command; this does not prove the omitted-zone semantics",
            "duration_limit_seconds":25,
        });
    }
    Ok(plan)
}

fn measure(device: &mut impl PrefixDevice, count: usize) -> Result<Vec<serde_json::Value>> {
    let mut out = Vec::new();
    let started = Instant::now();
    let black = vec![[0; 3]; count];
    for reverse in [false, true] {
        for level in [8, 64] {
            for n in lengths(count)? {
                for short in if reverse {
                    [true, false]
                } else {
                    [false, true]
                } {
                    let brightness = device.query(0x08, &[])?;
                    ensure!(
                        brightness.len() == 1 && brightness[0] > 0,
                        "Invalid brightness readback"
                    );
                    let prefix = vec![[level; 3]; n];
                    let mut full = black.clone();
                    full[..n].copy_from_slice(&prefix);
                    let mut samples = Vec::new();
                    for _ in 0..SAMPLES {
                        ensure!(
                            started.elapsed() < Duration::from_secs(25),
                            "Short probe duration limit reached"
                        );
                        device.frame(&black)?;
                        samples.push(if short {
                            device.prefix(&prefix)?
                        } else {
                            device.frame(&full)?
                        });
                    }
                    out.push(serde_json::json!({
                        "prefix_zones":n,"short":short,"reverse_pair_order":reverse,
                        "raw_neutral_code":level,"payload_bytes":if short {n*3} else {count*3},
                        "controller_brightness_readback":brightness[0],"samples":samples,
                    }));
                }
            }
        }
    }
    Ok(out)
}

fn observe(
    device: &mut impl PrefixDevice,
    count: usize,
    name: &str,
    mut hold: impl FnMut(Duration),
) -> Result<Vec<serde_json::Value>> {
    let (seed, prefix) = observation(name, count)?;
    let brightness = device.query(0x08, &[])?;
    ensure!(
        brightness.len() == 1 && brightness[0] > 0,
        "Invalid brightness readback"
    );
    eprintln!(
        "{name}: FULL SEED now for 3 seconds; then short prefix for {OBSERVE_SECONDS} seconds"
    );
    let full = device.frame(&vec![seed; count])?;
    hold(Duration::from_secs(3));
    let short = device.prefix(&vec![prefix; count / 4])?;
    eprintln!("{name}: SHORT PREFIX ACK received; observe omitted remainder now");
    hold(Duration::from_secs(OBSERVE_SECONDS));
    Ok(vec![serde_json::json!({
        "observation":name,"prefix_zones":count/4,"controller_brightness_readback":brightness[0],
        "full_seed_transaction":full,"short_transaction":short,
        "omitted_zone_observation":"Requires operator report; not inferred from ACK",
    })])
}

pub fn run(store: &Store, observation: Option<&str>) -> Result<()> {
    let description = plan(store, observation)?;
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    let outcome = guarded(&mut strip, c.device_zone_count, Some(10), |device| {
        if let Some(name) = observation {
            observe(device, c.device_zone_count, name, std::thread::sleep)
        } else {
            measure(device, c.device_zone_count)
        }
    });
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Short-payload test or restoration failed"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[derive(Default)]
    struct Fake {
        frames: Vec<Vec<[u8; 3]>>,
        prefixes: Vec<Vec<[u8; 3]>>,
        fail_prefix: bool,
        restored: bool,
    }
    impl Device for Fake {
        fn query(&mut self, command: u8, _: &[u8]) -> Result<Vec<u8>> {
            Ok(match command {
                0x06 => vec![0],
                0x08 => vec![16],
                0x09 | 0x07 => vec![],
                _ => panic!("Unexpected command"),
            })
        }
        fn frame(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
            assert_eq!(colors.len(), 48);
            self.frames.push(colors.to_vec());
            Ok(TransactionTimes::default())
        }
        fn restore(&mut self, power: &[u8], brightness: &[u8]) -> bool {
            assert_eq!(power, &[0]);
            assert_eq!(brightness, &[16]);
            self.restored = true;
            true
        }
    }
    impl PrefixDevice for Fake {
        fn prefix(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
            assert!(!colors.is_empty() && colors.len() < 48);
            self.prefixes.push(colors.to_vec());
            ensure!(!self.fail_prefix, "Injected missing prefix ACK");
            Ok(TransactionTimes::default())
        }
    }
    #[test]
    fn observation_sends_only_one_prefix_and_full_black_cleanup_even_on_failure() {
        for fail in [false, true] {
            let mut fake = Fake {
                fail_prefix: fail,
                ..Default::default()
            };
            let out = guarded(&mut fake, 48, Some(10), |d| {
                observe(d, 48, "red-prefix", |_| {})
            });
            assert_eq!(fake.prefixes, vec![vec![[64, 0, 0]; 12]]);
            assert_eq!(
                fake.frames,
                vec![vec![[0; 3]; 48], vec![[0, 0, 64]; 48], vec![[0; 3]; 48]]
            );
            assert!(fake.restored);
            assert_eq!(out["error"].is_null(), !fail);
            assert_eq!(out["black_cleanup_acknowledged"], true);
        }
    }
    #[test]
    fn measured_pairs_reset_with_full_black_and_cover_report_boundaries() {
        assert_eq!(lengths(48).unwrap(), vec![1, 12, 20, 21, 24, 41, 42, 47]);
        assert!(lengths(7).is_err());
        assert!(lengths(256).is_err());
        let mut fake = Fake::default();
        let rows = measure(&mut fake, 48).unwrap();
        assert_eq!(rows.len(), 64);
        assert_eq!(fake.prefixes.len(), 384);
        assert_eq!(fake.frames.len(), 1152);
        let mut i = 0;
        while i < fake.frames.len() {
            assert!(fake.frames[i].iter().flatten().all(|v| *v == 0));
            i += 1;
            if i < fake.frames.len() && fake.frames[i].iter().flatten().any(|v| *v != 0) {
                i += 1;
            }
        }
        for row in rows {
            assert_eq!(row["samples"].as_array().unwrap().len(), 12);
        }
    }
}
