//! Bounded diagnostic overhead only; no capture, USB or optical claims.
use nanoleaf_native::response::{Responses, Sample, WINDOW};
use std::{hint::black_box, time::Instant};
fn main() {
    let count = 600_000;
    let mut responses = Responses::default();
    let start = Instant::now();
    let mut summaries = 0;
    for n in 0..count {
        let ms = ((n * 137) % 1049) as f64 / 100.0;
        responses.record(
            black_box(Sample {
                capture_ms: ms,
                processing_ms: ms / 2.0,
                queue_ms: ms / 4.0,
                usb_ms: ms * 2.0,
                to_write_ms: ms * 3.0,
                to_ack_ms: ms * 4.0,
            }),
            n % 3 == 0,
        );
        if n % 60 == 59 {
            black_box(responses.summary());
            summaries += 1;
        }
    }
    let elapsed = start.elapsed().as_secs_f64();
    println!(
        "{}",
        serde_json::json!({
            "scope":"Synthetic varying timings; record each update, summarize every 60. No capture, USB, app-wide CPU, power or optical measurement.",
            "records":count,"summaries":summaries,"retained_per_source_kind":WINDOW,
            "retained_sample_bytes":2*WINDOW*std::mem::size_of::<Sample>(),
            "elapsed_seconds":elapsed,"microseconds_per_record_amortized":elapsed*1e6/count as f64
        })
    );
}
