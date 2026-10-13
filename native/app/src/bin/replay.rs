//! Offline complete-path attribution, with frame I/O explicitly outside kernel timing.
use anyhow::{ensure, Context, Result};
use nanoleaf_core::protocol::{encode_zone_frame, ChannelOrder};
use nanoleaf_native::{capture::Frame, config::Store, pipeline::Pipeline};
use serde::Deserialize;
use std::{io::Read, path::PathBuf, time::Instant};
#[derive(Deserialize)]
struct Manifest {
    config: PathBuf,
    frames: Vec<PathBuf>,
    repeats: usize,
    warmup: usize,
}
fn frame(path: &std::path::Path) -> Result<Frame> {
    let mut f = std::fs::File::open(path)?;
    let size = f.metadata()?.len();
    ensure!(
        (32..=128 * 1024 * 1024).contains(&size),
        "Invalid frame file size"
    );
    let mut header = [0; 32];
    f.read_exact(&mut header)?;
    ensure!(
        &header[..8] == b"NSRGB001",
        "Expected explicit SDR RGB8 frame"
    );
    let integer =
        |offset| u64::from_le_bytes(header[offset..offset + 8].try_into().unwrap()) as usize;
    let w = integer(8);
    let h = integer(16);
    let stride = integer(24);
    ensure!(
        w > 0
            && h > 0
            && stride >= w.checked_mul(3).context("Width overflow")?
            && stride.checked_mul(h) == Some(size as usize - 32),
        "Invalid frame geometry"
    );
    let mut data = vec![0; size as usize - 32];
    f.read_exact(&mut data)?;
    let pixels = if stride == w * 3 {
        data
    } else {
        data.chunks_exact(stride)
            .flat_map(|row| row[..w * 3].iter().copied())
            .collect()
    };
    Ok(Frame {
        width: w,
        height: h,
        pixels,
    })
}
fn main() -> Result<()> {
    let path = std::env::args_os().nth(1).context("Manifest required")?;
    let manifest: Manifest = serde_json::from_slice(&std::fs::read(path)?)?;
    let c = Store::load(&manifest.config)?.config;
    ensure!(
        !manifest.frames.is_empty()
            && manifest.frames.len() <= 240
            && manifest.repeats <= 20
            && manifest.warmup <= 20,
        "Invalid bounded replay"
    );
    let order = ChannelOrder::parse(&c.output_channel_order)?;
    let mut warm = Pipeline::default();
    for file in manifest.frames.iter().cycle().take(manifest.warmup) {
        warm.process(&frame(file)?, &c)?;
    }
    drop(warm);
    let mut runs = Vec::new();
    for _ in 0..manifest.repeats {
        let mut pipeline = Pipeline::default();
        let mut samples = Vec::new();
        for file in &manifest.frames {
            let input = frame(file)?;
            let start = Instant::now();
            let output = pipeline.process(std::hint::black_box(&input), &c)?;
            let tlv = encode_zone_frame(&output.colors, c.device_zone_count, order)?;
            let total_ms = start.elapsed().as_secs_f64() * 1000.0;
            samples.push(serde_json::json!({"total_ms":total_ms,"sampling_ms":output.times.sampling_ms,"colour_ms":output.times.colour_ms,"mixed_ms":output.times.mixed_ms,"palette_ms":output.times.palette_ms,"sampled":output.sampled,"colors":output.colors,"modes":output.modes,"tlv":tlv}));
        }
        runs.push(samples);
    }
    let proc = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
    let memory: Vec<_> = proc
        .lines()
        .filter(|l| l.starts_with("VmRSS:") || l.starts_with("VmHWM:"))
        .collect();
    println!(
        "{}",
        serde_json::json!({"scope":"Complete native SDR colour and TLV path, excluding capture, USB, UI and frame I/O","runs":runs,"memory":memory})
    );
    Ok(())
}
