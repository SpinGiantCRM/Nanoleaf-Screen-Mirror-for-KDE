//! Bounded operator-only, low-brightness acknowledged HID timing experiment.
//! Requires a stopped native service; no capture, configuration writes or payload logs.
use anyhow::{ensure, Context, Result};
use nanoleaf_native::{config::Store, probe};
use std::path::PathBuf;
fn main() -> Result<()> {
    let path = PathBuf::from(
        std::env::args_os()
            .nth(1)
            .context("Existing config required; stop mirroring first")?,
    );
    let store = Store::load(&path)?;
    ensure!(
        (1..=512).contains(&store.config.device_zone_count),
        "Manual zone count required"
    );
    let args: Vec<_> = std::env::args().skip(2).collect();
    if args.first().is_some_and(|s| s == "--ack-shape") {
        let run = match args.as_slice() {
            [_] => false,
            [_, run] if run == "--run" => true,
            _ => anyhow::bail!("Use usb_bench CONFIG --ack-shape [--run]"),
        };
        probe::ack_path::packet_shape(&store, run)?;
        return Ok(());
    }
    if args.first().is_some_and(|s| s == "--ack-brightness") {
        let run = match args.as_slice() {
            [_] => false,
            [_, run] if run == "--run" => true,
            _ => anyhow::bail!("Use usb_bench CONFIG --ack-brightness [--run]"),
        };
        probe::ack_path::brightness(&store, run)?;
        return Ok(());
    }
    if args.first().is_some_and(|s| s == "--ack-pacing") {
        let run = match args.as_slice() {
            [_] => false,
            [_, run] if run == "--run" => true,
            _ => anyhow::bail!("Use usb_bench CONFIG --ack-pacing [--run]"),
        };
        probe::ack_path::pacing(&store, run)?;
        return Ok(());
    }
    if args.first().is_some_and(|s| s == "--ack-control") {
        let run = match args.as_slice() {
            [_] => false,
            [_, run] if run == "--run" => true,
            _ => anyhow::bail!("Use usb_bench CONFIG --ack-control [--run]"),
        };
        probe::ack_path::control_read(&store, run)?;
        return Ok(());
    }
    if args
        .first()
        .is_some_and(|s| s == "--ack-path" || s == "--ack-output")
    {
        match args.as_slice() {
            [_] => println!(
                "{}",
                serde_json::to_string_pretty(&probe::ack_path::plan(
                    &store,
                    args[0] == "--ack-output"
                )?)?
            ),
            [_, run] if run == "--run" => probe::ack_path::run(&store, args[0] == "--ack-output")?,
            _ => anyhow::bail!("Use usb_bench CONFIG --ack-path|--ack-output [--run]"),
        }
        return Ok(());
    }
    if args.first().is_some_and(|s| s == "--short-payloads") {
        let (observe, run) = match args.as_slice() {
            [_] => (None, false),
            [_, run] if run == "--run" => (None, true),
            [_, flag, name] if flag == "--observe" => (Some(name.as_str()), false),
            [_, flag, name, run] if flag == "--observe" && run == "--run" => (Some(name.as_str()), true),
            _ => anyhow::bail!("Use usb_bench CONFIG --short-payloads [--observe red-prefix|black-prefix|green-prefix] [--run]"),
        };
        if run {
            probe::short_payload::run(&store, observe)?;
        } else {
            println!(
                "{}",
                serde_json::to_string_pretty(&probe::short_payload::plan(&store, observe)?)?
            );
        }
        return Ok(());
    }
    if args
        .first()
        .is_some_and(|s| s == "--positions" || s == "--repeat-response")
    {
        let positions = args[0] == "--positions";
        match args.as_slice() {
            [_] => println!(
                "{}",
                serde_json::to_string_pretty(&if positions {
                    probe::positions::plan(&store)?
                } else {
                    probe::repeat_response::plan(&store)?
                })?
            ),
            [_, run] if run == "--run" => {
                if positions {
                    probe::positions::run(&store)?
                } else {
                    probe::repeat_response::run(&store)?
                }
            }
            _ => anyhow::bail!("Use usb_bench CONFIG --positions|--repeat-response [--run]"),
        }
        return Ok(());
    }
    ensure!(
        args.len() <= 1,
        "Use usb_bench CONFIG [--content | --positions [--run]]"
    );
    let content = match args.first().map(String::as_str) {
        None => false,
        Some("--content") => true,
        _ => anyhow::bail!("Use usb_bench CONFIG [--content]"),
    };
    probe::usb_timing(&store, content)
}
