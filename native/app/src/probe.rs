//! Bounded operator diagnostics for capture, colour and USB attribution.
pub mod levels;
pub mod positions;
pub mod repeat_response;
use crate::{capture::KwinCapture, config::Store, pipeline::Pipeline};
use anyhow::{ensure, Context, Result};
use std::{
    path::Path,
    time::{Duration, Instant},
};

/// Read-only controller identity. Fixed query whitelist; no mode switches,
/// firmware writes, resets, lighting output or configuration edits.
pub fn usb_information(store: &Store) -> Result<()> {
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    let firmware = strip.request(0x0a, &[])?;
    let hardware = strip.request(0x0b, &[]);
    let manufacturer = strip.request(0x0d, &[]);
    let power = strip.request(0x06, &[])?;
    let brightness = strip.request(0x08, &[])?;
    ensure!(
        power.len() == 1 && power[0] <= 1 && brightness.len() == 1 && brightness[0] <= 100,
        "Invalid controller power/brightness response"
    );
    let hardware_error = hardware.as_ref().err().map(ToString::to_string);
    let manufacturer_error = manufacturer.as_ref().err().map(ToString::to_string);
    let hardware = hardware.ok();
    let manufacturer = manufacturer.ok();
    let version = decode_firmware_version(&firmware)?;
    ensure!(
        hardware.as_ref().is_none_or(|v| v.len() == 2)
            && manufacturer.as_ref().is_none_or(|v| v.len() == 1),
        "Unexpected optional identity response size"
    );
    println!(
        "{}",
        serde_json::json!({
            "scope": "Read-only documented identity queries; no LED or configuration changes; no DFU/reset/erase/program commands",
            "model": strip.model,
            "manual_zones": c.device_zone_count,
            "reported_zones_diagnostic_only": strip.reported_count,
            "firmware_raw": firmware,
            "firmware_major": version.0,
            "firmware_minor": version.1,
            "controller_power": power[0],
            "controller_brightness": brightness[0],
            "hardware_raw": hardware,
            "hardware_ascii": hardware.as_deref()
                .and_then(|v| std::str::from_utf8(v).ok())
                .filter(|s| s.bytes().all(|c| c.is_ascii_digit())),
            "hardware_query_error": hardware_error,
            "manufacturer_query_error": manufacturer_error,
            "manufacturer_raw": manufacturer,
            "manufacturer_ascii": manufacturer.as_deref()
                .and_then(|v| std::str::from_utf8(v).ok())
                .filter(|s| s.bytes().all(|c| c.is_ascii_alphanumeric())),
            "read_only": true,
        })
    );
    Ok(())
}
/// The manufacturer's firmware byte uses binary nibbles, not decimal/BCD text.
pub fn decode_firmware_version(bytes: &[u8]) -> Result<(u8, u8)> {
    ensure!(
        bytes.len() == 1,
        "Firmware query must return one version byte"
    );
    Ok((bytes[0] >> 4, bytes[0] & 15))
}

/// Operator experiment: isolate command cadence from capture/colour processing.
/// Every packet remains acknowledged. Settings are read only; controller power
/// and brightness are restored and verified even after a transaction failure.
pub fn usb_timing(store: &Store, content: bool) -> Result<()> {
    let _owner = crate::service::acquire_output(&crate::service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = crate::device::Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    let power = strip.request(0x06, &[])?;
    let brightness = strip.request(0x08, &[])?;
    let result = (|| -> Result<Vec<serde_json::Value>> {
        strip.request(0x09, &[10])?;
        strip.request(0x07, &[1])?;
        let mut cases = Vec::new();
        if content {
            let patterns = [
                ("black", [0, 0, 0], c.device_zone_count),
                ("grey-1", [1, 1, 1], c.device_zone_count),
                ("grey-8", [8, 8, 8], c.device_zone_count),
                ("grey-64", [64, 64, 64], c.device_zone_count),
                ("grey-255", [255, 255, 255], c.device_zone_count),
                ("red-8", [8, 0, 0], c.device_zone_count),
                ("green-8", [0, 8, 0], c.device_zone_count),
                ("blue-8", [0, 0, 8], c.device_zone_count),
                ("grey-first-zone", [8, 8, 8], 1),
                ("grey-quarter", [8, 8, 8], (c.device_zone_count / 4).max(1)),
                ("grey-half", [8, 8, 8], (c.device_zone_count / 2).max(1)),
            ];
            for reverse in [false, true] {
                let indices: Vec<_> = if reverse {
                    (0..patterns.len()).rev().collect()
                } else {
                    (0..patterns.len()).collect()
                };
                for index in indices {
                    let (label, rgb, lit) = patterns[index];
                    let mut frame = vec![[0; 3]; c.device_zone_count];
                    frame[..lit].fill(rgb);
                    std::thread::sleep(Duration::from_millis(70));
                    let mut samples = Vec::new();
                    for _ in 0..16 {
                        strip.frame(&frame)?;
                        samples.push(
                            strip
                                .last_frame_transaction
                                .clone()
                                .context("Missing USB timing")?,
                        );
                    }
                    cases.push(serde_json::json!({"pattern":label,"reverse_pass":reverse,"samples":samples}));
                }
            }
            return Ok(cases);
        }
        // Reversed repeat separates cadence effects from simple warm-up/order.
        for period_ms in [
            0.0, 16.666667, 22.222222, 33.333333, 33.333333, 22.222222, 16.666667, 0.0,
        ] {
            for alternating in [false, true] {
                std::thread::sleep(Duration::from_millis(70));
                let mut samples = Vec::new();
                let mut previous = None;
                let mut deadline = Instant::now();
                for frame in 0..24 {
                    std::thread::sleep(deadline.saturating_duration_since(Instant::now()));
                    let started = Instant::now();
                    let rgb = if alternating && frame % 2 == 1 {
                        [0; 3]
                    } else {
                        [8; 3]
                    };
                    strip.frame(&vec![rgb; c.device_zone_count])?;
                    let timing = strip
                        .last_frame_transaction
                        .as_ref()
                        .context("Missing USB timing")?;
                    samples.push(serde_json::json!({"frame":frame,"since_previous_start_ms":previous.map(|p|started.duration_since(p).as_secs_f64()*1000.0),"transaction":timing}));
                    previous = Some(started);
                    deadline = (deadline + Duration::from_secs_f64(period_ms / 1000.0))
                        .max(Instant::now());
                }
                cases.push(serde_json::json!({"target_period_ms":period_ms,"alternating_black":alternating,"samples":samples}));
            }
        }
        Ok(cases)
    })();
    let black_ok = strip.black().is_ok();
    let restored = strip.restore_controller(&power, &brightness);
    println!(
        "{}",
        serde_json::json!({"scope":"Generated low-brightness grey/black; acknowledged existing USB protocol; no capture or optical measurement","model":strip.model,"manual_zones":c.device_zone_count,"controller_restored":restored,"black_cleanup_acknowledged":black_ok,"cases":result.as_ref().ok(),"error":result.as_ref().err().map(ToString::to_string)})
    );
    result?;
    ensure!(restored && black_ok, "Controller restoration failed");
    Ok(())
}
pub fn capture(path: &Path, seconds: f64) -> Result<()> {
    ensure!(
        seconds.is_finite() && (0.1..=30.0).contains(&seconds),
        "Probe duration must be .1 to 30 seconds"
    );
    let store = Store::load(path)?;
    let capture = KwinCapture::new(store.config.capture_monitor.clone())?;
    let mut pipeline = Pipeline::default();
    let start = Instant::now();
    let mut samples = Vec::new();
    let mut size = (0, 0);
    let mut first_ms = 0.0;
    while start.elapsed() < Duration::from_secs_f64(seconds) {
        let frame_start = Instant::now();
        let (frame, capture_times) = capture.capture_timed()?;
        let capture_ms = frame_start.elapsed().as_secs_f64() * 1000.0;
        size = (frame.width, frame.height);
        let out = pipeline.process(&frame, &store.config)?;
        if samples.is_empty() {
            first_ms = start.elapsed().as_secs_f64() * 1000.0;
        }
        samples.push(serde_json::json!({"capture_ms":capture_ms,"reply_ms":capture_times.reply_ms,"pipe_ms":capture_times.pipe_ms,"decode_ms":capture_times.decode_ms,"qt_format":capture_times.format,"processing_ms":out.times.total_ms,"sampling_ms":out.times.sampling_ms,"colour_ms":out.times.colour_ms,"response_ms":frame_start.elapsed().as_secs_f64()*1000.0}));
        let target = Duration::from_secs_f64(1.0 / store.config.fps as f64);
        if let Some(remaining) = target.checked_sub(frame_start.elapsed()) {
            std::thread::sleep(remaining);
        }
    }
    let proc = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    let memory: Vec<_> = proc
        .lines()
        .filter(|l| l.starts_with("VmRSS:") || l.starts_with("VmHWM:") || l.starts_with("Threads:"))
        .collect();
    println!(
        "{}",
        serde_json::json!({"scope":"Real KWin SDR screenshot and complete native colour path; no USB or optical measurements","width":size.0,"height":size.1,"elapsed_seconds":start.elapsed().as_secs_f64(),"first_output_ms":first_ms,"frames":samples.len(),"samples":samples,"memory":memory})
    );
    Ok(())
}

/// Exercise the complete streaming worker without opening a HID device.
pub fn stream_capture(path: &Path, seconds: f64) -> Result<()> {
    ensure!(
        seconds.is_finite() && (0.1..=30.0).contains(&seconds),
        "Probe duration must be .1 to 30 seconds"
    );
    let mut config = Store::load(path)?.config;
    config.capture_backend = "xdg-portal".into();
    crate::pipeline::validate_mirroring(&config)?;
    let (tx, rx) = std::sync::mpsc::channel();
    let producer = crate::worker::Producer::spawn(config, tx);
    let started = Instant::now();
    let mut samples = Vec::new();
    let mut error = None;
    let mut first_frame: Option<Instant> = None;
    while first_frame
        .map(|first| first.elapsed() < Duration::from_secs_f64(seconds))
        .unwrap_or_else(|| started.elapsed() < Duration::from_secs(120))
    {
        let _ = rx.recv_timeout(Duration::from_millis(100));
        if let Some(frame) = producer.take() {
            match frame {
                Ok(frame) => {
                    first_frame.get_or_insert_with(Instant::now);
                    samples.push(serde_json::json!({"capture_ms":frame.capture_ms,"processing":frame.times,"prepared_age_ms":frame.started.elapsed().as_secs_f64()*1000.0,"backend":frame.backend,"manual_output_count":frame.colors.len(),"parity_verified":frame.parity_verified,"highlight_cache":frame.highlight_cache,"source_reused":frame.source_reused,"response_clock":frame.response_clock,"capture_stages":frame.capture_stages,"source_presentation_age_ms":frame.source_pts_ns.map(|pts| {let now=rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);((now.tv_sec as i128*1_000_000_000+now.tv_nsec as i128)-pts as i128) as f64/1_000_000.0})}));
                }
                Err(e) => {
                    error = Some(e);
                    break;
                }
            }
        }
    }
    let dropped = producer.dropped();
    drop(producer);
    println!(
        "{}",
        serde_json::json!({"scope":"Supervised streaming worker and full native colour processing; no USB or optical measurement, no saved pixels/config changes","frames":samples.len(),"duration_ms":started.elapsed().as_secs_f64()*1000.0,"first_frame_ms":first_frame.map(|f|f.duration_since(started).as_secs_f64()*1000.0),"dropped_prepared_frames":dropped,"samples":samples,"error":error})
    );
    ensure!(
        error.is_none() && !samples.is_empty(),
        "Streaming capture probe failed: {}",
        error.unwrap_or_else(|| "No frames".into())
    );
    Ok(())
}
