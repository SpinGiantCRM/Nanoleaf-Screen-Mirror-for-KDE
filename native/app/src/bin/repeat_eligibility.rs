//! Hardware-free opportunity census through the saved calibrated colour pipeline.
use anyhow::{ensure, Context, Result};
use nanoleaf_native::{
    capture::Frame,
    config::Store,
    pipeline::{quantize_acknowledged, Pipeline},
    repeat::Repeat,
};
use std::{path::PathBuf, time::Instant};

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let path = PathBuf::from(
        args.next()
            .context("Use repeat_eligibility EXISTING_CONFIG; no capture or USB")?,
    );
    ensure!(args.next().is_none(), "One existing config path required");
    let config = Store::load(&path)?.config;
    ensure!(
        (1..=512).contains(&config.device_zone_count),
        "Manual zone count required"
    );
    let mut eligible = 0;
    let mut eligible_nonblack = 0;
    let mut rejected = 0;
    for code in 0..=255u8 {
        let frame = Frame {
            width: 96,
            height: 54,
            pixels: [code; 3].repeat(96 * 54),
        };
        let output = Pipeline::default().process(&frame, &config)?;
        let colors = if config.blue_noise_dither {
            quantize_acknowledged(&output.unquantized_rgb, 0)
        } else {
            output.colors
        };
        let mut repeat = Repeat::default();
        let now = Instant::now();
        repeat.acknowledged(&colors, now);
        if repeat.can_suppress(
            &colors,
            Some(&output.unquantized_rgb),
            config.blue_noise_dither,
            now,
        ) {
            eligible += 1;
            if colors.iter().any(|p| *p != [0; 3]) {
                eligible_nonblack += 1;
            }
        } else {
            rejected += 1;
        }
    }
    println!(
        "{}",
        serde_json::json!({"scope":"Offline census of 256 cold uniform neutral SDR sources at 96x54 through the saved calibrated pipeline; assumes an identical initial frame was acknowledged. Not capture, USB, a performance benchmark, real-content eligibility or emitted colour validation. No user coefficients or output RGB values serialized.","cases":256,"manual_zones":config.device_zone_count,"dithering":config.blue_noise_dither,"eligible_phase_invariant_cases":eligible,"eligible_nonblack_cases":eligible_nonblack,"rejected_cases":rejected})
    );
    Ok(())
}
