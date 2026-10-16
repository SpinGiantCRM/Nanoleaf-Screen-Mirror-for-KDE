//! Synthetic ACK stalls through the real transport; no capture or HID device.
use anyhow::Result;
use nanoleaf_native::device::{transact_timed_with_progress, ReportIo};
use std::{
    cell::Cell,
    sync::mpsc,
    time::{Duration, Instant},
};

struct Delayed {
    started: Cell<Option<Instant>>,
    writes: Cell<usize>,
    acknowledge: bool,
}
impl ReportIo for Delayed {
    fn write(&self, report: &[u8]) -> Result<usize> {
        if self.started.get().is_none() {
            self.started.set(Some(Instant::now()));
        }
        self.writes.set(self.writes.get() + 1);
        Ok(report.len())
    }
    fn read_timeout(&self, buffer: &mut [u8], timeout: i32) -> Result<usize> {
        let Some(started) = self.started.get() else {
            return Ok(0);
        };
        let remaining = Duration::from_millis(200).saturating_sub(started.elapsed());
        let sleep = Duration::from_millis(timeout.max(0) as u64);
        std::thread::sleep(if self.acknowledge {
            sleep.min(remaining)
        } else {
            sleep
        });
        if self.acknowledge && started.elapsed() >= Duration::from_millis(200) {
            buffer[..4].copy_from_slice(&[0x82, 0, 1, 0]);
            Ok(4)
        } else {
            Ok(0)
        }
    }
}

fn main() -> Result<()> {
    let mut rows = Vec::new();
    for acknowledge in [true, false] {
        for progress in [false, true] {
            for _ in 0..4 {
                let io = Delayed {
                    started: Cell::new(None),
                    writes: Cell::new(0),
                    acknowledge,
                };
                let (tx, rx) = mpsc::channel();
                let sender = std::thread::spawn(move || {
                    std::thread::sleep(Duration::from_millis(20));
                    let _ = tx.send(Instant::now());
                });
                let mut stopped = None;
                let start = Instant::now();
                let result = transact_timed_with_progress(&io, 2, &[17; 144], || {
                    if progress && stopped.is_none() {
                        if let Ok(requested) = rx.try_recv() {
                            stopped = Some((requested, Instant::now()));
                        }
                    }
                });
                let transaction_ms = start.elapsed().as_secs_f64() * 1000.0;
                let (requested, accepted) = match stopped {
                    Some(value) => value,
                    None => (rx.recv()?, Instant::now()),
                };
                sender.join().expect("Stop sender");
                assert_eq!(result.is_ok(), acknowledge);
                assert_eq!(io.writes.get(), 3);
                rows.push(serde_json::json!({
                    "progress_enabled":progress,"simulated_acknowledgement":acknowledge,
                    "cancellation_callback_after_stop_ms":accepted.duration_since(requested).as_secs_f64()*1000.0,
                    "transaction_ms":transaction_ms,"report_writes":io.writes.get(),
                    "transaction_acknowledged":result.is_ok()
                }));
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({
            "scope":"Simulated Stop at 20 ms during a 200 ms ACK or a real 250 ms transport timeout, using injected ReportIo. Compares cancellation after transaction vs between bounded reads. No HID, capture process, light-output, optical or whole-app measurement; cleanup-black timing excluded.",
            "trials":rows
        })
    );
    Ok(())
}
