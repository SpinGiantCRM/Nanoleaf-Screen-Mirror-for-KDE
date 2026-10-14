//! Offline scene-step settling; not capture/USB or optical latency.
use anyhow::{Context, Result};
use nanoleaf_core::colour::decode_srgb;
use nanoleaf_native::{capture::Frame, config::Store, pipeline::Pipeline};
use std::{path::PathBuf, time::Duration};
fn frame(rgb: [u8; 3]) -> Frame {
    Frame {
        width: 64,
        height: 48,
        pixels: rgb.repeat(64 * 48),
    }
}
fn mean(rgb: &[[f32; 3]], gamma: f64) -> [f64; 3] {
    std::array::from_fn(|c| {
        rgb.iter()
            .map(|v| {
                f64::from(decode_srgb(
                    ((f64::from(v[c]) / 255.0).powf(gamma.clamp(1.0, 4.0)) * 255.0) as f32,
                ))
            })
            .sum::<f64>()
            / rgb.len() as f64
    })
}
fn distance(a: [f64; 3], b: [f64; 3]) -> f64 {
    a.into_iter()
        .zip(b)
        .map(|(a, b)| (a - b).powi(2))
        .sum::<f64>()
        .sqrt()
}
fn main() -> Result<()> {
    let path = PathBuf::from(
        std::env::args_os()
            .nth(1)
            .context("Existing config path required")?,
    );
    let saved = Store::load(&path)?.config;
    let mut cases = vec![];
    for (label, from, to) in [
        ("grey rise", [64; 3], [192; 3]),
        ("grey fall", [192; 3], [64; 3]),
        ("small grey change", [128; 3], [132; 3]),
        ("modest grey change", [100; 3], [120; 3]),
        ("red to blue", [180, 40, 20], [20, 60, 200]),
        ("black cut", [192; 3], [0; 3]),
        ("from black", [0; 3], [192; 3]),
    ] {
        let mut direct = saved.clone();
        direct.enable_fast_response();
        let target = mean(
            &Pipeline::default()
                .process(&frame(to), &direct)?
                .unquantized_rgb,
            direct.led_calibration_profile_sdr.led_gamma,
        );
        for mode in [
            "saved",
            "no accumulation",
            "maximum response",
            "maximum without accumulation",
        ] {
            let mut c = saved.clone();
            if matches!(mode, "no accumulation" | "maximum without accumulation") {
                c.zone_temporal_accumulation = false;
            }
            if matches!(mode, "maximum response" | "maximum without accumulation") {
                c.smoothing = 1.0;
            }
            let mut p = Pipeline::default();
            let mut start = [0.0; 3];
            for _ in 0..30 {
                start = mean(
                    &p.process(&frame(from), &c)?.unquantized_rgb,
                    c.led_calibration_profile_sdr.led_gamma,
                );
            }
            let initial = distance(start, target);
            let period = 1.0 / f64::from(c.fps);
            let mut rows = vec![];
            for tick in 1..=240 {
                p.set_temporal_elapsed(Duration::from_secs_f64(period));
                let out = p.process(&frame(to), &c)?;
                let remaining = distance(
                    mean(
                        &out.unquantized_rgb,
                        c.led_calibration_profile_sdr.led_gamma,
                    ),
                    target,
                ) / initial.max(1e-12);
                rows.push(serde_json::json!({"tick":tick,"software_elapsed_ms":tick as f64*period*1000.0,"remaining_error":remaining,"first_zone":out.unquantized_rgb[0],"processing_ms":out.times.total_ms}));
            }
            let reached = |limit: f64| {
                rows.iter()
                    .find(|r| r["remaining_error"].as_f64().unwrap() <= limit)
                    .map(|r| r["software_elapsed_ms"].clone())
            };
            cases.push(serde_json::json!({"scene":label,"mode":mode,"fps":c.fps,"accumulation":c.zone_temporal_accumulation,"responsiveness":c.smoothing,"t50_ms":reached(0.5),"t90_ms":reached(0.1),"t99_ms":reached(0.01),"first_update_remaining_error":rows[0]["remaining_error"],"samples":rows}));
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Generated uniform SDR step with existing calibration/mapping. Configured transfer-model RGB error against a fresh unfiltered target. Synthetic source-clock settling at configured FPS, not wall-clock or optical latency; excludes capture/USB. No screen images or config writes.","cases":cases})
    );
    Ok(())
}
