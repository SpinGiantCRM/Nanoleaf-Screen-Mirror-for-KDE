//! Bounded read-only capture/colour attribution. No screen pixels or USB are saved.
use crate::{capture::KwinCapture, config::Store, pipeline::Pipeline};
use anyhow::{ensure, Result};
use std::{
    path::Path,
    time::{Duration, Instant},
};
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
