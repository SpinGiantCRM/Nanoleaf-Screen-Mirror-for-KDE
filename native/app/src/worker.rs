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
pub struct Prepared {
    pub colors: Vec<[u8; 3]>,
    pub times: ProcessingTimes,
    pub capture_ms: f64,
    pub started: Instant,
}
struct Latest {
    value: Mutex<Option<Result<Prepared, String>>>,
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
            *slot = Some(value);
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
}
impl Producer {
    pub fn spawn(config: Config, tx: mpsc::Sender<Control>) -> Self {
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
            while !cancel.load(Ordering::Acquire) {
                let start = Instant::now();
                let output = (|| -> anyhow::Result<Prepared> {
                    let frame = capture.capture()?;
                    let capture_ms = start.elapsed().as_secs_f64() * 1000.0;
                    if cancel.load(Ordering::Acquire) {
                        anyhow::bail!("Capture cancelled");
                    }
                    if let Ok(sent) = actual_sent.lock() {
                        pipeline.override_sent(&sent);
                    }
                    let out = pipeline.process(&frame, &config)?;
                    Ok(Prepared {
                        colors: out.colors,
                        times: out.times,
                        capture_ms,
                        started: start,
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
        }
    }
    pub fn take(&self) -> Option<Result<Prepared, String>> {
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
            slot.put(
                Ok(Prepared {
                    colors: vec![[n; 3]; 48],
                    times: ProcessingTimes::default(),
                    capture_ms: 0.0,
                    started: Instant::now(),
                }),
                &tx,
            );
        }
        assert_eq!(rx.try_iter().count(), 1);
        assert_eq!(slot.dropped.load(Ordering::Relaxed), 2);
        assert_eq!(
            slot.value.lock().unwrap().take().unwrap().unwrap().colors,
            vec![[2; 3]; 48]
        );
    }
}
