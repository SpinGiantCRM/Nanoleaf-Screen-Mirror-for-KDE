//! Offline fixture/benchmark executable. No capture or USB operations.

use nanoleaf_core::protocol::{self, ChannelOrder};
use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect, ZoneSample};
use std::error::Error;
use std::ffi::OsStr;
use std::fs::File;
use std::hint::black_box;
use std::io::Read;
use std::path::Path;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const FRAME_MAGIC: &[u8; 8] = b"NSRGB001";
const ZONE_MAGIC: &[u8; 8] = b"NZONE001";

fn read_bounded(path: &Path, limit: usize) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err("fixture exceeds size limit".into());
    }
    Ok(bytes)
}

fn u64_at(bytes: &[u8], offset: usize) -> Result<u64> {
    Ok(u64::from_le_bytes(
        bytes
            .get(offset..offset + 8)
            .ok_or("truncated header")?
            .try_into()?,
    ))
}

fn parse_hex(text: &str) -> Result<Vec<u8>> {
    if text.len() % 2 != 0 || text.len() > (protocol::MAX_PAYLOAD + 3) * 2 {
        return Err("invalid hex length".into());
    }
    text.as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let high = char::from(pair[0]).to_digit(16).ok_or("invalid hex")?;
            let low = char::from(pair[1]).to_digit(16).ok_or("invalid hex")?;
            Ok(((high << 4) | low) as u8)
        })
        .collect()
}

fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(text, "{byte:02x}").expect("writing to String cannot fail");
    }
    text
}

fn utf8(arg: &OsStr) -> Result<&str> {
    arg.to_str().ok_or_else(|| "non-UTF8 argument".into())
}

fn metrics(samples: &[f64]) -> String {
    let mut sorted = samples.to_vec();
    sorted.sort_by(f64::total_cmp);
    let n = sorted.len();
    let median = if n % 2 == 0 {
        (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
    } else {
        sorted[n / 2]
    };
    let p95 = sorted[((n - 1) as f64 * 0.95).round_ties_even() as usize];
    format!(
        "{{\"samples_ms\":{samples:?},\"median_ms\":{median},\"p95_ms\":{p95},\"max_ms\":{}}}",
        sorted[n - 1]
    )
}

fn memory() -> String {
    let Ok(text) = std::fs::read_to_string("/proc/self/smaps_rollup") else {
        return "null".into();
    };
    let get = |key: &str| -> Option<u64> {
        text.lines()
            .find(|line| line.starts_with(key))?
            .split_whitespace()
            .nth(1)?
            .parse()
            .ok()
    };
    match (get("Rss:"), get("Pss:")) {
        (Some(rss), Some(pss)) => format!("{{\"rss\":{rss},\"pss\":{pss}}}"),
        _ => "null".into(),
    }
}

fn sample(args: &[std::ffi::OsString]) -> Result<()> {
    if args.len() != 6 {
        return Err("sample requires FRAME ZONES ITERATIONS WARMUP".into());
    }
    let frame_blob = read_bounded(Path::new(&args[2]), 128 * 1024 * 1024)?;
    if frame_blob.get(..8) != Some(FRAME_MAGIC) {
        return Err("expected explicit SDR sRGB RGB8 fixture magic".into());
    }
    let width = usize::try_from(u64_at(&frame_blob, 8)?)?;
    let height = usize::try_from(u64_at(&frame_blob, 16)?)?;
    let stride = usize::try_from(u64_at(&frame_blob, 24)?)?;
    let data = frame_blob.get(32..).ok_or("truncated frame header")?;
    let frame = SdrRgb8Frame::new(data, width, height, stride)?;
    let zone_blob = read_bounded(Path::new(&args[3]), 1024 * 1024)?;
    if zone_blob.get(..8) != Some(ZONE_MAGIC) {
        return Err("invalid zone fixture magic".into());
    }
    let count = usize::try_from(u64_at(&zone_blob, 8)?)?;
    let manual_count = usize::try_from(u64_at(&zone_blob, 16)?)?;
    if count == 0 || count > protocol::MAX_PAYLOAD / 3 || manual_count != count {
        return Err("manual zone count must match the fixture's zone count".into());
    }
    if zone_blob.len() != 24 + count * 32 {
        return Err("invalid zone fixture length".into());
    }
    let mut zones = Vec::with_capacity(count);
    for bytes in zone_blob[24..].chunks_exact(32) {
        let component = |offset| i64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
        zones.push(ZoneRect {
            x: component(0),
            y: component(8),
            width: component(16),
            height: component(24),
        });
    }
    let iterations: usize = utf8(&args[4])?.parse()?;
    let warmup: usize = utf8(&args[5])?.parse()?;
    if !(1..=100_000).contains(&iterations) || warmup > 10_000 {
        return Err("iterations/warmup outside offline benchmark bounds".into());
    }
    let sampler = SdrSampler::default();
    let mut output = vec![ZoneSample::default(); count];
    for _ in 0..warmup {
        sampler.sample_into(black_box(&frame), black_box(&zones), black_box(&mut output))?;
    }
    let mut samples = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        let start = Instant::now();
        sampler.sample_into(black_box(&frame), black_box(&zones), black_box(&mut output))?;
        black_box(&output);
        samples.push(start.elapsed().as_secs_f64() * 1000.0);
    }
    let colors: Vec<[u8; 3]> = output.iter().map(|sample| sample.srgb).collect();
    let request = protocol::encode_zone_frame(&colors, manual_count, ChannelOrder::parse("grb")?)?;
    print!("{{\"encoding\":\"sdr_srgb_u8\",\"build_rustc\":\"{}\",\"metrics\":{},\"memory_kib\":{},\"grb_tlv_hex\":\"{}\",\"zones\":[", env!("NANOLEAF_CORE_BUILD_RUSTC"), metrics(&samples), memory(), hex(&request));
    for (i, sample) in output.iter().enumerate() {
        if i != 0 {
            print!(",");
        }
        print!(
            "{{\"rgb\":{:?},\"linear\":{:?},\"variance\":{},\"pixels\":{}}}",
            sample.srgb, sample.linear_rgb, sample.encoded_variance, sample.pixel_count
        );
    }
    println!("]}}");
    Ok(())
}

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    match args.get(1).and_then(|arg| arg.to_str()) {
        Some("sample") => sample(&args),
        Some(kind @ ("request" | "response")) if args.len() == 4 => {
            let command = u8::from_str_radix(utf8(&args[2])?, 16)?;
            let bytes = parse_hex(utf8(&args[3])?)?;
            let output = if kind == "request" {
                protocol::encode_request(command, &bytes)?
            } else {
                protocol::parse_response(command, &bytes)?.to_vec()
            };
            println!("{}", hex(&output));
            Ok(())
        }
        _ => Err(
            "usage: sample FRAME ZONES ITERATIONS WARMUP | request/response CMD_HEX BYTES_HEX"
                .into(),
        ),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
