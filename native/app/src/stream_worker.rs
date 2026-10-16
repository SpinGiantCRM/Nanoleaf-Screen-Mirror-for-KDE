//! Supervised capture child. No GPU handles or full-screen buffers enter the HID actor.
use super::*;
use anyhow::{ensure, Context, Result};
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
    process::{Command, Stdio},
};
#[derive(serde::Deserialize)]
struct Record {
    schema: u32,
    colors: Vec<[u8; 3]>,
    #[serde(default)]
    unquantized_rgb: Option<Vec<[f32; 3]>>,
    times: ProcessingTimes,
    capture_ms: f64,
    prepared_age_ms: f64,
    source_pts_ns: Option<i64>,
    backend: String,
    parity_exact: Option<bool>,
    #[serde(default)]
    highlight_cache: (usize, u64),
    #[serde(default)]
    source_reused: bool,
    #[serde(default)]
    reuse_started_ns: Option<i64>,
    #[serde(default)]
    frame_started_ns: Option<i64>,
    #[serde(default)]
    capture_stages: Option<CaptureStages>,
}
fn prepared(record: Record, manual: usize) -> Result<Prepared> {
    ensure!(
        matches!(record.schema, 1..=3) && record.colors.len() == manual,
        "Capture protocol/count mismatch"
    );
    ensure!(
        [
            record.capture_ms,
            record.prepared_age_ms,
            record.times.total_ms,
            record.times.sampling_ms,
            record.times.colour_ms,
            record.times.mixed_ms,
            record.times.palette_ms
        ]
        .iter()
        .all(|v| v.is_finite() && (0.0..=10_000.0).contains(v)),
        "Invalid capture timings"
    );
    if let Some(rgb) = &record.unquantized_rgb {
        ensure!(
            rgb.len() == manual
                && rgb
                    .iter()
                    .flatten()
                    .all(|v| v.is_finite() && (0.0..=255.0).contains(v)),
            "Invalid unquantized colour frame"
        );
    }
    ensure!(
        record.highlight_cache.0 <= 16 * 1024 * 1024,
        "Invalid highlight cache accounting"
    );
    ensure!(
        record
            .capture_stages
            .as_ref()
            .is_none_or(CaptureStages::valid),
        "Invalid GPU capture timings"
    );
    ensure!(
        record.backend.starts_with("xdg-portal / Vulkan DMA-BUF /") && record.backend.len() <= 128,
        "Unknown capture colour contract"
    );
    ensure!(
        !record.source_reused || record.schema >= 2,
        "Cached-source output requires protocol version 2 or later"
    );
    let timing_pts = if record.schema == 3 {
        ensure!(
            record.reuse_started_ns.is_none(),
            "Ambiguous capture work clock"
        );
        Some(
            record
                .frame_started_ns
                .context("Capture work timestamp missing")?,
        )
    } else if record.source_reused {
        Some(
            record
                .reuse_started_ns
                .context("Cached-source output has no work timestamp")?,
        )
    } else {
        ensure!(
            record.reuse_started_ns.is_none(),
            "Fresh source has a cached-work timestamp"
        );
        record.source_pts_ns.filter(|&p| p >= 0)
    };
    ensure!(
        record.schema == 3 || record.frame_started_ns.is_none(),
        "Unexpected capture work timestamp in legacy protocol"
    );
    let age = if let Some(pts) = timing_pts {
        let now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
        let delta = (now.tv_sec as i128 * 1_000_000_000 + now.tv_nsec as i128) - pts as i128;
        ensure!(
            (0..10_000_000_000).contains(&delta),
            "Invalid capture {} timestamp: age {:.3} ms",
            if record.schema == 3 { "work" } else { "legacy" },
            delta as f64 / 1_000_000.0
        );
        Duration::from_nanos(delta as u64)
    } else {
        Duration::from_secs_f64(record.prepared_age_ms / 1000.0)
    };
    Ok(Prepared {
        unquantized_rgb: record.unquantized_rgb,
        colors: record.colors,
        times: record.times,
        capture_ms: record.capture_ms,
        started: Instant::now()
            .checked_sub(age)
            .context("Capture timestamp overflow")?,
        backend: record.backend,
        parity_verified: record.parity_exact == Some(true),
        highlight_cache: record.highlight_cache,
        source_reused: record.source_reused,
        response_clock: if record.source_reused {
            "cached-work"
        } else if record.schema == 3 {
            "capture-work"
        } else if record.source_pts_ns.is_some_and(|pts| pts >= 0) {
            "source-presentation"
        } else {
            "legacy-work"
        },
        source_pts_ns: record.source_pts_ns.filter(|&p| p >= 0),
        capture_stages: record.capture_stages,
    })
}
fn helper() -> Result<PathBuf> {
    let executable = std::env::current_exe()?.canonicalize()?;
    let installed = executable
        .parent()
        .context("No application directory")?
        .join("nanoleaf-native-capture");
    if installed.is_file() {
        return Ok(installed);
    }
    for ancestor in executable.ancestors() {
        if ancestor.join("app/Cargo.toml").is_file()
            && ancestor.join("stream-probe/Cargo.toml").is_file()
        {
            let development = ancestor.join("stream-probe/target/release/nanoleaf-stream-probe");
            ensure!(
                development.is_file(),
                "Build the native streaming capture helper first"
            );
            return Ok(development);
        }
    }
    anyhow::bail!("Native capture helper is not installed; use KWin capture")
}
impl Producer {
    pub(super) fn spawn_stream(config: Config, tx: mpsc::Sender<Control>) -> Self {
        let latest = Arc::new(Latest {
            value: Mutex::new(None),
            dropped: AtomicU64::new(0),
            missed: AtomicU64::new(0),
        });
        let stop = Arc::new(AtomicBool::new(false));
        let sent = Arc::new(Mutex::new(Vec::new()));
        let (feedback_notify, feedback_ready) = mpsc::sync_channel(1);
        let launch = (|| -> Result<_> {
            let mut child = Command::new(helper()?)
                .arg("--worker")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()?;
            let mut input = child.stdin.take().context("No capture control pipe")?;
            if let Err(error) = (|| -> Result<()> {
                serde_json::to_writer(&mut input, &config)?;
                input.write_all(b"\n")?;
                input.flush()?;
                Ok(())
            })() {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
            let output = child.stdout.take().context("No capture output pipe")?;
            let errors = child.stderr.take().context("No capture error pipe")?;
            Ok((Arc::new(Mutex::new(child)), input, output, errors))
        })();
        let (child, thread) = match launch {
            Err(error) => {
                let slot = latest.clone();
                let message = error.to_string();
                (
                    None,
                    std::thread::spawn(move || slot.put(Err(message), &tx)),
                )
            }
            Ok((child, mut input, output, errors)) => {
                let (cancel, actual) = (stop.clone(), sent.clone());
                let error_text = Arc::new(Mutex::new(String::new()));
                let error_sink = error_text.clone();
                // Always drain stderr so a warning cannot block capture. Retain
                // only a bounded diagnostic tail; never log config or frame bytes.
                std::thread::spawn(move || {
                    let mut reader = BufReader::new(errors);
                    let mut chunk = [0_u8; 1024];
                    loop {
                        match reader.read(&mut chunk) {
                            Ok(0) | Err(_) => break,
                            Ok(n) => {
                                if let Ok(mut text) = error_sink.lock() {
                                    text.push_str(&String::from_utf8_lossy(&chunk[..n]));
                                    if text.len() > 8192 {
                                        let at = text.len() - 4096;
                                        let at = text
                                            .char_indices()
                                            .find_map(|(i, _)| (i >= at).then_some(i))
                                            .unwrap_or(text.len());
                                        text.drain(..at);
                                    }
                                }
                            }
                        }
                    }
                });
                std::thread::spawn(move || {
                    forward_feedback(&mut input, &actual, &cancel, feedback_ready);
                });
                let (slot, cancel, process) = (latest.clone(), stop.clone(), child.clone());
                let thread = std::thread::spawn(move || {
                    let mut reader = BufReader::new(output);
                    let outcome = (|| -> Result<()> {
                        while !cancel.load(Ordering::Acquire) {
                            let mut line = String::new();
                            let count = reader.by_ref().take(32769).read_line(&mut line)?;
                            if count == 0 {
                                anyhow::bail!(
                                    "Capture worker ended before the next frame: {}",
                                    error_text
                                        .lock()
                                        .ok()
                                        .map(|s| s.trim().to_owned())
                                        .filter(|s| !s.is_empty())
                                        .unwrap_or_else(|| "Screen sharing ended".into())
                                );
                            }
                            ensure!(line.len() <= 32768, "Oversized capture response");
                            let value =
                                prepared(serde_json::from_str(&line)?, config.device_zone_count)?;
                            if cancel.load(Ordering::Acquire) {
                                break;
                            }
                            slot.put(Ok(value), &tx);
                        }
                        Ok(())
                    })();
                    if !cancel.load(Ordering::Acquire) {
                        if let Err(error) = outcome {
                            slot.put(Err(error.to_string()), &tx);
                        }
                    }
                    if let Ok(mut child) = process.lock() {
                        let _ = child.kill();
                    }
                    // Never wait while holding the mutex used by Stop/preview.
                    loop {
                        let done = process
                            .lock()
                            .ok()
                            .is_none_or(|mut child| !matches!(child.try_wait(), Ok(None)));
                        if done {
                            break;
                        }
                        std::thread::sleep(Duration::from_millis(50));
                    }
                });
                (Some(child), thread)
            }
        };
        Self {
            latest,
            stop,
            thread,
            sent,
            feedback_notify: Some(feedback_notify),
            child,
        }
    }
}

/// Forward complete actual-ACK feedback, coalescing wakes rather than colours.
/// The HID actor only updates the bounded latest slot and never waits for stdin.
fn forward_feedback(
    input: &mut impl Write,
    actual: &Mutex<Vec<[u8; 3]>>,
    cancel: &AtomicBool,
    ready: mpsc::Receiver<()>,
) {
    let mut previous = Vec::new();
    while ready.recv().is_ok() {
        if cancel.load(Ordering::Acquire) {
            break;
        }
        let value = actual.lock().ok().map(|v| v.clone()).unwrap_or_default();
        if !value.is_empty() && value != previous {
            previous = value;
            if serde_json::to_writer(&mut *input, &previous).is_err()
                || input.write_all(b"\n").is_err()
                || input.flush().is_err()
            {
                break;
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ack_feedback_coalesces_to_complete_latest_colours_without_blocking_actor() {
        let actual = Mutex::new(vec![[15, 16, 24]; 48]);
        let (notify, ready) = mpsc::sync_channel(1);
        notify.try_send(()).unwrap();
        let latest: Vec<_> = (0..48).map(|i| [i, i + 1, i + 2]).collect();
        *actual.lock().unwrap() = latest.clone();
        assert!(matches!(
            notify.try_send(()),
            Err(mpsc::TrySendError::Full(()))
        ));
        drop(notify);
        let mut output = Vec::new();
        forward_feedback(&mut output, &actual, &AtomicBool::new(false), ready);
        let decoded: Vec<[u8; 3]> = serde_json::from_slice(&output).unwrap();
        assert_eq!(decoded, latest);
        assert_eq!(output.iter().filter(|&&b| b == b'\n').count(), 1);
    }

    #[test]
    fn ack_feedback_waits_without_polling_and_disconnect_or_cancel_releases_stdin() {
        let (notify, ready) = mpsc::sync_channel(1);
        let (done, exited) = mpsc::channel();
        let thread = std::thread::spawn(move || {
            let mut output = Vec::new();
            forward_feedback(
                &mut output,
                &Mutex::new(Vec::new()),
                &AtomicBool::new(false),
                ready,
            );
            done.send(output).unwrap();
        });
        assert!(matches!(exited.try_recv(), Err(mpsc::TryRecvError::Empty)));
        drop(notify);
        assert!(exited
            .recv_timeout(Duration::from_secs(1))
            .unwrap()
            .is_empty());
        thread.join().unwrap();

        let (notify, ready) = mpsc::sync_channel(1);
        notify.try_send(()).unwrap();
        let mut output = Vec::new();
        forward_feedback(
            &mut output,
            &Mutex::new(vec![[255; 3]; 48]),
            &AtomicBool::new(true),
            ready,
        );
        assert!(output.is_empty());
    }

    #[test]
    fn child_frames_are_bounded_typed_and_manual_count_authoritative() {
        let record = || Record {
            schema: 1,
            colors: vec![[128; 3]; 4],
            unquantized_rgb: None,
            times: ProcessingTimes::default(),
            capture_ms: 1.0,
            prepared_age_ms: 2.0,
            source_pts_ns: None,
            parity_exact: None,
            highlight_cache: (0, 0),
            backend: "xdg-portal / Vulkan DMA-BUF / direct SDR samples".into(),
            source_reused: false,
            reuse_started_ns: None,
            frame_started_ns: None,
            capture_stages: None,
        };
        assert!(prepared(record(), 4).is_ok());
        let mut r = record();
        r.capture_stages = Some(CaptureStages {
            total_ms: f64::NAN,
            ..Default::default()
        });
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.capture_stages = Some(CaptureStages {
            sampling_ms: -1.0,
            ..Default::default()
        });
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.capture_stages = Some(CaptureStages {
            total_ms: 1.5,
            cache_hit: true,
            ..Default::default()
        });
        assert!(prepared(r, 4).unwrap().capture_stages.unwrap().cache_hit);
        assert!(prepared(record(), 5).is_err());
        let mut r = record();
        r.unquantized_rgb = Some(vec![[128.25; 3]; 4]);
        assert!(prepared(r, 4).is_ok());
        let mut r = record();
        r.unquantized_rgb = Some(vec![[f32::NAN; 3]; 4]);
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.unquantized_rgb = Some(vec![[256.0; 3]; 4]);
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.unquantized_rgb = Some(vec![[128.0; 3]; 5]);
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.schema = 4;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.times.total_ms = f64::NAN;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.backend = "untagged raw HDR".into();
        assert!(prepared(r, 4).is_err());
    }

    #[test]
    fn unchanged_source_has_its_own_work_clock_and_cannot_bypass_protocol_guards() {
        let now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
        let now_ns = now.tv_sec * 1_000_000_000 + now.tv_nsec;
        let record = || Record {
            schema: 2,
            colors: vec![[128; 3]; 4],
            unquantized_rgb: Some(vec![[128.25; 3]; 4]),
            times: ProcessingTimes::default(),
            capture_ms: 0.0,
            prepared_age_ms: 1.0,
            source_pts_ns: Some(now_ns - 30_000_000_000),
            backend: "xdg-portal / Vulkan DMA-BUF / direct SDR samples".into(),
            parity_exact: None,
            highlight_cache: (0, 0),
            source_reused: true,
            reuse_started_ns: Some(now_ns),
            frame_started_ns: None,
            capture_stages: None,
        };
        let out = prepared(record(), 4).unwrap();
        assert!(out.source_reused);
        assert!(out.started.elapsed() < Duration::from_secs(1));
        let mut r = record();
        r.schema = 1;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.reuse_started_ns = None;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.reuse_started_ns = Some(now_ns - 30_000_000_000);
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.reuse_started_ns = Some(now_ns + 30_000_000_000);
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.source_reused = false;
        assert!(prepared(r, 4).is_err());
    }
    #[test]
    fn capture_work_deadline_is_independent_of_display_presentation_age() {
        let now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
        let now_ns = now.tv_sec * 1_000_000_000 + now.tv_nsec;
        let record = || Record {
            schema: 3,
            colors: vec![[128; 3]; 4],
            unquantized_rgb: None,
            times: ProcessingTimes::default(),
            capture_ms: 1.0,
            prepared_age_ms: 2.0,
            source_pts_ns: Some(now_ns - 30_000_000_000),
            backend: "xdg-portal / Vulkan DMA-BUF / direct SDR samples".into(),
            parity_exact: None,
            highlight_cache: (0, 0),
            source_reused: false,
            reuse_started_ns: None,
            frame_started_ns: Some(now_ns - 2_000_000),
            capture_stages: None,
        };
        for pts in [
            None,
            Some(-1),
            Some(now_ns - 30_000_000_000),
            Some(now_ns + 30_000_000_000),
        ] {
            let mut r = record();
            r.source_pts_ns = pts;
            let out = prepared(r, 4).unwrap();
            assert_eq!(out.response_clock, "capture-work");
            assert!(out.started.elapsed() >= Duration::from_millis(2));
            assert!(out.started.elapsed() < Duration::from_secs(1));
        }
        let mut cached = record();
        cached.source_reused = true;
        assert_eq!(prepared(cached, 4).unwrap().response_clock, "cached-work");
        // A fresh display timestamp cannot launder an old/future/missing work packet.
        for work in [
            None,
            Some(-1),
            Some(now_ns - 30_000_000_000),
            Some(now_ns + 30_000_000_000),
        ] {
            let mut r = record();
            r.source_pts_ns = Some(now_ns);
            r.frame_started_ns = work;
            assert!(prepared(r, 4).is_err());
        }
        let mut r = record();
        r.reuse_started_ns = Some(now_ns);
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.schema = 2;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.frame_started_ns = None;
        r.schema = 2;
        assert!(prepared(r, 4).is_err()); // legacy stale-source guard retained
    }
}
