//! Capture and colour share one worker; only the latest small colour frame queues.
//! USB remains owned by the service actor. No full-screen frame crosses threads.
use crate::{
    capture::KwinCapture,
    config::Config,
    pipeline::{Pipeline, ProcessingTimes},
    service::Control,
};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    mpsc, Arc, Mutex,
};
use std::time::{Duration, Instant};
/// Numeric capture attribution only; never contains pixels or configuration.
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct CaptureStages {
    pub total_ms: f64,
    pub producer_fence_ms: f64,
    pub import_ms: f64,
    pub acquire_ms: f64,
    pub analysis_ms: f64,
    pub zone_update_ms: f64,
    pub sampling_ms: f64,
    pub release_ms: f64,
    pub cache_hit: bool,
    pub analysis_bytes: u64,
    #[serde(default)]
    pub analysis_summary_bytes: u64,
    pub analysis_batches: u64,
}
impl CaptureStages {
    pub fn valid(&self) -> bool {
        [
            self.total_ms,
            self.producer_fence_ms,
            self.import_ms,
            self.acquire_ms,
            self.analysis_ms,
            self.zone_update_ms,
            self.sampling_ms,
            self.release_ms,
        ]
        .into_iter()
        .all(|v| v.is_finite() && (0.0..=10_000.0).contains(&v))
    }
}
pub struct Prepared {
    pub unquantized_rgb: Option<Vec<[f32; 3]>>,
    pub colors: Vec<[u8; 3]>,
    pub times: ProcessingTimes,
    pub capture_ms: f64,
    pub started: Instant,
    pub backend: String,
    pub parity_verified: bool,
    pub highlight_cache: (usize, u64),
    pub source_reused: bool,
    pub response_clock: &'static str,
    pub source_pts_ns: Option<i64>,
    pub capture_stages: Option<CaptureStages>,
}
struct Latest {
    value: Mutex<Option<(Result<Prepared, String>, Instant)>>,
    dropped: AtomicU64,
    missed: AtomicU64,
}
impl Latest {
    fn put(&self, value: Result<Prepared, String>, tx: &mpsc::Sender<Control>) {
        if let Ok(mut slot) = self.value.lock() {
            let notify = slot.is_none();
            if !notify {
                self.dropped.fetch_add(1, Ordering::Relaxed);
            }
            *slot = Some((value, Instant::now()));
            if notify {
                let _ = tx.send(Control::FrameReady);
            }
        }
    }
}
pub struct Producer {
    latest: Arc<Latest>,
    stop: Arc<AtomicBool>,
    thread: std::thread::JoinHandle<()>,
    sent: Arc<Mutex<Vec<[u8; 3]>>>,
    child: Option<Arc<Mutex<std::process::Child>>>,
}
impl Producer {
    pub fn spawn(config: Config, tx: mpsc::Sender<Control>) -> Self {
        if config.capture_backend == "xdg-portal" {
            return Self::spawn_stream(config, tx);
        }
        let latest = Arc::new(Latest {
            value: Mutex::new(None),
            dropped: AtomicU64::new(0),
            missed: AtomicU64::new(0),
        });
        let stop = Arc::new(AtomicBool::new(false));
        let sent = Arc::new(Mutex::new(Vec::new()));
        let (slot, cancel, actual_sent) = (latest.clone(), stop.clone(), sent.clone());
        let thread = std::thread::spawn(move || {
            let capture = match KwinCapture::new(config.capture_monitor.clone()) {
                Ok(c) => c,
                Err(e) => {
                    slot.put(Err(e.to_string()), &tx);
                    return;
                }
            };
            let mut pipeline = Pipeline::default();
            let period = Duration::from_secs_f64(1.0 / config.fps as f64);
            let mut deadline = Instant::now();
            let mut source_time = None;
            while !cancel.load(Ordering::Acquire) {
                let start = Instant::now();
                let output = (|| -> anyhow::Result<Prepared> {
                    let frame = capture.capture()?;
                    let current_time = Instant::now();
                    if let Some(previous) = source_time {
                        pipeline.set_temporal_elapsed(current_time - previous);
                    }
                    source_time = Some(current_time);
                    let capture_ms = start.elapsed().as_secs_f64() * 1000.0;
                    if cancel.load(Ordering::Acquire) {
                        anyhow::bail!("Capture cancelled");
                    }
                    if let Ok(sent) = actual_sent.lock() {
                        pipeline.override_sent(&sent);
                    }
                    let out = pipeline.process(&frame, &config)?;
                    Ok(Prepared {
                        unquantized_rgb: Some(out.unquantized_rgb),
                        colors: out.colors,
                        times: out.times,
                        capture_ms,
                        started: start,
                        backend: "kwin-dbus (SDR display-referred)".into(),
                        parity_verified: false,
                        highlight_cache: out.highlight_cache,
                        source_reused: false,
                        response_clock: "capture-request",
                        source_pts_ns: None,
                        capture_stages: None,
                    })
                })();
                if cancel.load(Ordering::Acquire) {
                    break;
                }
                match output {
                    Ok(out) => slot.put(Ok(out), &tx),
                    Err(e) => {
                        slot.put(Err(e.to_string()), &tx);
                        break;
                    }
                }
                deadline += period;
                if deadline < Instant::now() {
                    slot.missed.fetch_add(1, Ordering::Relaxed);
                    deadline = Instant::now();
                }
                std::thread::park_timeout(deadline.saturating_duration_since(Instant::now()));
            }
            // Owned capture descriptors and the connection close on their worker.
        });
        Self {
            latest,
            stop,
            thread,
            sent,
            child: None,
        }
    }
    pub fn take(&self) -> Option<Result<Prepared, String>> {
        self.take_with_ready_time().map(|(value, _)| value)
    }
    /// The timestamp belongs to the retained packet, including after overwrite.
    pub fn take_with_ready_time(&self) -> Option<(Result<Prepared, String>, Instant)> {
        self.latest.value.lock().ok()?.take()
    }
    pub fn acknowledge(&self, colors: &[[u8; 3]]) {
        if let Ok(mut s) = self.sent.lock() {
            *s = colors.to_vec();
        }
    }
    pub fn missed(&self) -> u64 {
        self.latest.missed.load(Ordering::Relaxed)
    }
    pub fn dropped(&self) -> u64 {
        self.latest.dropped.load(Ordering::Relaxed)
    }
}
impl Drop for Producer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        self.thread.thread().unpark();
        if let Some(child) = &self.child {
            if let Ok(mut child) = child.lock() {
                let _ = child.kill();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn latest_colour_slot_is_bounded_coalesces_and_wakes_only_once() {
        let (tx, rx) = mpsc::channel();
        let slot = Latest {
            value: Mutex::new(None),
            dropped: AtomicU64::new(0),
            missed: AtomicU64::new(0),
        };
        for n in 0..3 {
            let before = Instant::now();
            slot.put(
                Ok(Prepared {
                    unquantized_rgb: None,
                    colors: vec![[n; 3]; 48],
                    times: ProcessingTimes::default(),
                    capture_ms: 0.0,
                    started: Instant::now(),
                    backend: "fixture".into(),
                    parity_verified: false,
                    highlight_cache: (0, 0),
                    source_reused: false,
                    response_clock: "fixture",
                    source_pts_ns: None,
                    capture_stages: None,
                }),
                &tx,
            );
            let at = slot.value.lock().unwrap().as_ref().unwrap().1;
            assert!(at >= before && at <= Instant::now());
            // Force an old marker: the next overwrite must replace its timing
            // as well as its colours, rather than measuring the first packet.
            if n < 2 {
                slot.value.lock().unwrap().as_mut().unwrap().1 = before - Duration::from_secs(1);
            }
        }
        assert_eq!(rx.try_iter().count(), 1);
        assert_eq!(slot.dropped.load(Ordering::Relaxed), 2);
        assert_eq!(
            slot.value.lock().unwrap().take().unwrap().0.unwrap().colors,
            vec![[2; 3]; 48]
        );
    }
}

#[path = "stream_worker.rs"]
mod stream;
