//! Same TLV and serial ACK; compare three hidraw writes with one USB transfer.
use super::levels::guarded;
use crate::config::Store;
use anyhow::{ensure, Result};
use std::time::{Duration, Instant};

const SAMPLES: usize = 16;
const ORDER: [bool; 4] = [false, true, true, false];

fn frames(count: usize) -> Vec<(&'static str, Vec<[u8; 3]>)> {
    vec![
        ("black", vec![[0; 3]; count]),
        ("neutral-8", vec![[8; 3]; count]),
        ("neutral-64", vec![[64; 3]; count]),
        (
            "varied",
            (0..count).map(|i| [(i % 65) as u8, 24, 48]).collect(),
        ),
    ]
}

pub fn plan(store: &Store, output_ioctl: bool) -> Result<serde_json::Value> {
    ensure!(
        store.config.device_vid == 0x37fa
            && store.config.device_pid == 0x8202
            && store.config.device_zone_count == 48,
        "ACK transfer probe requires the tested 48-zone NL82K2"
    );
    let mut description = serde_json::json!({
        "scope":"Generated known colour commands; unchanged RGB bytes, one outstanding command with matching ACK; no capture or firmware writes",
        "hypothesis":"One hidraw write lets Linux transfer the same 64/64/19-byte endpoint packets without separate blocking submissions",
        "order":ORDER,"true_means":"single transfer","samples_per_case":SAMPLES,
        "warmup_samples_per_case":2,"patterns":["black","neutral-8","neutral-64","varied"],
        "transactions":4*ORDER.len()*SAMPLES,"maximum_raw_channel":64,
        "requested_controller_brightness":10,"manual_zones":48,
        "duration_limit_seconds":25,"hardware_run_requires":"--ack-path --run",
        "restoration":"Black cleanup and original power/brightness readback; no saved configuration writes",
        "optical_measurement":false,"daily_transport_changed":false,
    });
    if output_ioctl {
        description["hypothesis"] = "Compare ordinary writes with HIDIOCSOUTPUT; do not assume the local kernel routes it through the control endpoint".into();
        description["true_means"] = "HIDIOCSOUTPUT reports".into();
        description["hardware_run_requires"] = "--ack-output --run".into();
    }
    Ok(description)
}

pub fn run(store: &Store, output_ioctl: bool) -> Result<()> {
    let description = plan(store, output_ioctl)?;
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    ensure!(
        strip.enable_short_updates(),
        "Controller firmware/hardware not verified for this experiment"
    );
    let mut cases = Vec::new();
    let mut resynchronized = None;
    let mut outcome = guarded(&mut strip, c.device_zone_count, Some(10), |d| {
        let result = (|| -> Result<()> {
            let start = Instant::now();
            for (pattern, frame) in frames(c.device_zone_count) {
                for (pass, single) in ORDER.into_iter().enumerate() {
                    let brightness = d.request(0x08, &[])?;
                    cases.push(serde_json::json!({"pattern":pattern,"pass":pass,
                        "candidate":single,"controller_brightness_readback":brightness,
                        "samples":[]}));
                    let samples = cases.last_mut().unwrap()["samples"].as_array_mut().unwrap();
                    for _ in 0..SAMPLES {
                        ensure!(
                            start.elapsed() < Duration::from_secs(25),
                            "ACK probe deadline reached"
                        );
                        samples.push(serde_json::to_value(d.probe_transfer(
                            &frame,
                            single && !output_ioctl,
                            single && output_ioctl,
                        )?)?);
                    }
                }
            }
            Ok(())
        })();
        if result.is_err() {
            // No uncertain retry. Allow the bounded ACK deadline to elapse,
            // then establish a distinct-command barrier before black cleanup.
            std::thread::sleep(Duration::from_millis(300));
            resynchronized = Some(d.request(0x0c, &[]).is_ok_and(|v| v == b"NL82K2"));
        }
        result?;
        Ok(vec![])
    });
    outcome["phases"] = cases.into();
    outcome["failure_resynchronized"] = resynchronized.into();
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "ACK transfer probe or restoration failed"
    );
    Ok(())
}

pub fn control_read(store: &Store, run: bool) -> Result<()> {
    let mut description = plan(store, false)?;
    description["scope"] = "HID GET_REPORT while idle and immediately after a colour write. Always require the ordinary serial interrupt ACK; never accept a control reply as an ACK. Generated capped colours, guarded controller restoration, no firmware/config writes.".into();
    description["hardware_run_requires"] = "--ack-control --run; known to block beyond the ACK deadline on the tested controller, never use in daily output".into();
    for key in [
        "hypothesis",
        "true_means",
        "order",
        "samples_per_case",
        "warmup_samples_per_case",
        "transactions",
    ] {
        description.as_object_mut().unwrap().remove(key);
    }
    if !run {
        println!("{description}");
        return Ok(());
    }
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    ensure!(strip.enable_short_updates(), "Untested controller contract");
    let original_power = strip.request(0x06, &[])?;
    let original_brightness = strip.request(0x08, &[])?;
    let read = strip.probe_control_read();
    let mut cases = Vec::new();
    let outcome = guarded(&mut strip, c.device_zone_count, Some(10), |d| {
        for (pattern, frame) in frames(c.device_zone_count) {
            ensure!(d.request(0x0c, &[])? == b"NL82K2", "Model barrier failed");
            let measurement = d.probe_control_ack(&frame)?;
            let failed = !measurement["error"].is_null();
            cases.push(serde_json::json!({"pattern":pattern,"measurement":measurement}));
            if failed {
                std::thread::sleep(Duration::from_millis(300));
                ensure!(
                    d.request(0x0c, &[])? == b"NL82K2",
                    "Failure resynchronization failed"
                );
                anyhow::bail!(
                    "Ordinary ACK deadline expired during control read; experiment rejected"
                );
            }
        }
        Ok(vec![])
    });
    let ordinary_queries_ok = strip.request(0x0c, &[]).is_ok_and(|v| v == b"NL82K2")
        && strip.request(0x06, &[]).is_ok_and(|v| v == original_power)
        && strip
            .request(0x08, &[])
            .is_ok_and(|v| v == original_brightness);
    println!(
        "{}",
        serde_json::json!({"scope":description["scope"],
            "control_read":read,"cases":cases,"outcome":outcome,
            "ordinary_queries_ok":ordinary_queries_ok})
    );
    ensure!(
        ordinary_queries_ok
            && outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Ordinary queries failed after control-read experiment"
    );
    Ok(())
}

pub fn pacing(store: &Store, run: bool) -> Result<()> {
    let mut description = plan(store, false)?;
    description.as_object_mut().unwrap().remove("hypothesis");
    description["scope"] = "Identical ordinary full-frame reports and serial ACKs; vary only gaps between the three writes. Judge total command time, not ACK-wait alone.".into();
    description["candidate_gaps_us"] = serde_json::json!([250, 500, 1000, 2000]);
    description["true_means"] = "candidate gap between writes".into();
    description["patterns"] = serde_json::json!(["neutral-8", "neutral-64"]);
    description["hardware_run_requires"] = "--ack-pacing --run".into();
    description["samples_per_case"] = 8.into();
    description["transactions"] = 256.into();
    if !run {
        println!("{description}");
        return Ok(());
    }
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    ensure!(strip.enable_short_updates(), "Untested controller contract");
    let mut cases = Vec::new();
    let outcome = guarded(&mut strip, c.device_zone_count, Some(10), |d| {
        let start = Instant::now();
        for level in [8, 64] {
            let frame = vec![[level; 3]; c.device_zone_count];
            for candidate_gap in [250, 500, 1000, 2000] {
                for candidate in ORDER {
                    let gap = if candidate { candidate_gap } else { 0 };
                    cases.push(serde_json::json!({"raw_neutral_code":level,"candidate_gap_us":candidate_gap,
                        "gap_us":gap,"samples":[]}));
                    let samples = cases.last_mut().unwrap()["samples"].as_array_mut().unwrap();
                    for _ in 0..8 {
                        ensure!(
                            start.elapsed() < Duration::from_secs(25),
                            "Pacing probe deadline reached"
                        );
                        samples.push(serde_json::to_value(d.probe_pacing(&frame, gap)?)?);
                    }
                }
            }
        }
        Ok(vec![])
    });
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome,"cases":cases})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Pacing probe or restoration failed"
    );
    Ok(())
}

pub fn brightness(store: &Store, run: bool) -> Result<()> {
    let mut description = plan(store, false)?;
    description["scope"] = "Test whether documented controller brightness changes receiver ACK work. Generated black/code-8 full frames only; no host colour compensation or saved calibration changes.".into();
    description["requested_brightness_levels"] = serde_json::json!([1, 16, 32, 64, 100, 255]);
    description["patterns"] = serde_json::json!(["black", "neutral-8"]);
    description["maximum_raw_channel"] = 8.into();
    description["samples_per_case"] = 8.into();
    description["transactions"] = 192.into();
    description["hardware_run_requires"] = "--ack-brightness --run".into();
    for key in [
        "hypothesis",
        "true_means",
        "order",
        "requested_controller_brightness",
    ] {
        description.as_object_mut().unwrap().remove(key);
    }
    if !run {
        println!("{description}");
        return Ok(());
    }
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    ensure!(strip.enable_short_updates(), "Untested controller contract");
    let mut cases = Vec::new();
    let outcome = guarded(&mut strip, c.device_zone_count, None, |d| {
        let start = Instant::now();
        let requests = [1, 16, 32, 64, 100, 255];
        for reverse in [false, true] {
            for index in 0..requests.len() {
                let requested = requests[if reverse {
                    requests.len() - 1 - index
                } else {
                    index
                }];
                d.request(0x09, &[requested])?;
                let readback = d.request(0x08, &[])?;
                ensure!(
                    readback.len() == 1,
                    "Invalid controller brightness readback"
                );
                for code in [0, 8] {
                    let frame = vec![[code; 3]; c.device_zone_count];
                    cases.push(
                        serde_json::json!({"reverse":reverse,"requested_brightness":requested,
                        "brightness_readback":readback[0],"raw_neutral_code":code,"samples":[]}),
                    );
                    let samples = cases.last_mut().unwrap()["samples"].as_array_mut().unwrap();
                    for _ in 0..8 {
                        ensure!(
                            start.elapsed() < Duration::from_secs(25),
                            "Brightness probe deadline reached"
                        );
                        d.frame(&frame)?;
                        samples.push(serde_json::to_value(
                            d.last_frame_transaction.as_ref().unwrap(),
                        )?);
                    }
                }
            }
        }
        Ok(vec![])
    });
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome,"cases":cases})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Brightness ACK probe or restoration failed"
    );
    Ok(())
}

pub fn packet_shape(store: &Store, run: bool) -> Result<()> {
    let mut description = plan(store, false)?;
    description["scope"]="Compare final padding and RGB-aligned fragmentation of the identical full TLV; ordinary serial ACK and no saved configuration edits".into();
    description["shapes"] = serde_json::json!([
        "reference-64-short-tail",
        "64-padded-tail",
        "63-short-tail",
        "60-short-tail"
    ]);
    description["hardware_run_requires"] = "--ack-shape --run".into();
    description["samples_per_case"] = 8.into();
    description["transactions"] = 384.into();
    description.as_object_mut().unwrap().remove("hypothesis");
    description["true_means"] = "candidate packet shape".into();
    if !run {
        println!("{description}");
        return Ok(());
    }
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    ensure!(strip.enable_short_updates(), "Untested controller contract");
    let mut cases = Vec::new();
    let mut failure_resynchronized = None;
    let outcome = guarded(&mut strip, c.device_zone_count, Some(10), |d| {
        let start = Instant::now();
        let result = (|| -> Result<()> {
            for (pattern, frame) in frames(c.device_zone_count) {
                for candidate_shape in 1..=3 {
                    for candidate in ORDER {
                        let shape = if candidate { candidate_shape } else { 0 };
                        cases.push(serde_json::json!({"pattern":pattern,"candidate_shape":candidate_shape,"shape":shape,"samples":[]}));
                        let samples = cases.last_mut().unwrap()["samples"].as_array_mut().unwrap();
                        for _ in 0..8 {
                            ensure!(
                                start.elapsed() < Duration::from_secs(25),
                                "Packet shape deadline reached"
                            );
                            samples
                                .push(serde_json::to_value(d.probe_packet_shape(&frame, shape)?)?);
                        }
                    }
                }
            }
            Ok(())
        })();
        if result.is_err() {
            std::thread::sleep(Duration::from_millis(300));
            failure_resynchronized = Some(d.request(0x0c, &[]).is_ok_and(|v| v == b"NL82K2"));
        }
        result?;
        Ok(vec![])
    });
    println!(
        "{}",
        serde_json::json!({"plan":description,"outcome":outcome,"cases":cases,"failure_resynchronized":failure_resynchronized})
    );
    ensure!(
        outcome["error"].is_null()
            && outcome["black_cleanup_acknowledged"] == true
            && outcome["controller_restored"] == true,
        "Packet-shape probe or restoration failed"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identical_bounded_frames_and_both_trial_orders() {
        let patterns = frames(48);
        assert_eq!(patterns.len(), 4);
        assert_eq!(ORDER, [false, true, true, false]);
        for (_, frame) in patterns {
            assert_eq!(frame.len(), 48);
            assert!(frame.iter().flatten().all(|v| *v <= 64));
        }
    }
}
