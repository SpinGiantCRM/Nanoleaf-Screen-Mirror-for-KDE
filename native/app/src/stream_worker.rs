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
    times: ProcessingTimes,
    capture_ms: f64,
    prepared_age_ms: f64,
    source_pts_ns: Option<i64>,
    backend: String,
    parity_exact: Option<bool>,
    #[serde(default)]
    highlight_cache: (usize, u64),
}
fn prepared(record: Record, manual: usize) -> Result<Prepared> {
    ensure!(
        record.schema == 1 && record.colors.len() == manual,
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
    ensure!(
        record.highlight_cache.0 <= 16 * 1024 * 1024,
        "Invalid highlight cache accounting"
    );
    ensure!(
        record.backend.starts_with("xdg-portal / Vulkan DMA-BUF /") && record.backend.len() <= 128,
        "Unknown capture colour contract"
    );
    let age = if let Some(pts) = record.source_pts_ns.filter(|&p| p >= 0) {
        let now = rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
        let delta = (now.tv_sec as i128 * 1_000_000_000 + now.tv_nsec as i128) - pts as i128;
        ensure!((0..10_000_000_000).contains(&delta), "Stale capture frame");
        Duration::from_nanos(delta as u64)
    } else {
        Duration::from_secs_f64(record.prepared_age_ms / 1000.0)
    };
    Ok(Prepared {
        colors: record.colors,
        times: record.times,
        capture_ms: record.capture_ms,
        started: Instant::now()
            .checked_sub(age)
            .context("Capture timestamp overflow")?,
        backend: record.backend,
        parity_verified: record.parity_exact == Some(true),
        highlight_cache: record.highlight_cache,
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
                    let mut previous = Vec::new();
                    while !cancel.load(Ordering::Acquire) {
                        let value = actual.lock().ok().map(|v| v.clone()).unwrap_or_default();
                        if !value.is_empty() && value != previous {
                            previous = value;
                            if serde_json::to_writer(&mut input, &previous).is_err()
                                || input.write_all(b"\n").is_err()
                                || input.flush().is_err()
                            {
                                break;
                            }
                        }
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    // Closing stdin also stops an orphaned child if its parent exits.
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
                                    "{}",
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
            child,
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn child_frames_are_bounded_typed_and_manual_count_authoritative() {
        let record = || Record {
            schema: 1,
            colors: vec![[128; 3]; 4],
            times: ProcessingTimes::default(),
            capture_ms: 1.0,
            prepared_age_ms: 2.0,
            source_pts_ns: None,
            parity_exact: None,
            highlight_cache: (0, 0),
            backend: "xdg-portal / Vulkan DMA-BUF / direct SDR samples".into(),
        };
        assert!(prepared(record(), 4).is_ok());
        assert!(prepared(record(), 5).is_err());
        let mut r = record();
        r.schema = 2;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.times.total_ms = f64::NAN;
        assert!(prepared(r, 4).is_err());
        let mut r = record();
        r.backend = "untagged raw HDR".into();
        assert!(prepared(r, 4).is_err());
    }
}
