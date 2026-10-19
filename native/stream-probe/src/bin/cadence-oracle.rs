//! Actual SPA loop/timer with synthetic output work; no display, capture or HID.
#[path = "../cadence.rs"]
mod cadence;
use anyhow::Result;
use std::time::{Duration, Instant};
fn main() -> Result<()> {
    pipewire::init();
    let mut cases = Vec::new();
    for fps in [30, 60, 144] {
        for legacy in [true, false] {
            let loop_ = pipewire::main_loop::MainLoopRc::new(None)?;
            let timer = loop_.loop_().add_timer(|_| {});
            let period = Duration::from_secs_f64(1.0 / f64::from(fps));
            let start = Instant::now();
            let mut last = start;
            let mut intervals = Vec::new();
            let mut wakes = 0;
            while start.elapsed() < Duration::from_secs(2) {
                let timeout = if legacy {
                    pipewire::loop_::Timeout::Finite(period.min(Duration::from_millis(100)))
                } else {
                    cadence::arm(
                        &timer,
                        cadence::remaining(Some(last), period, Instant::now()),
                    )?
                };
                loop_.loop_().iterate(timeout);
                wakes += 1;
                let now = Instant::now();
                if now.duration_since(last) >= period {
                    intervals.push(now.duration_since(last).as_secs_f64() * 1000.0);
                    last = now;
                    // Same bounded synthetic finishing work in both cases.
                    std::thread::sleep(Duration::from_micros(100));
                }
            }
            let seconds = start.elapsed().as_secs_f64();
            cases.push(serde_json::json!({"target_fps":fps,"legacy_full_period_poll":legacy,"seconds":seconds,"updates":intervals.len(),"updates_per_second":intervals.len() as f64/seconds,"wakeups":wakes,"interval_ms":intervals}));
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Actual PipeWire SPA loop and timer, no server/capture/HID; unchanged-source scheduling plus equal 100us synthetic work. Not optical latency or end-to-end app cadence.","cases":cases})
    );
    Ok(())
}
