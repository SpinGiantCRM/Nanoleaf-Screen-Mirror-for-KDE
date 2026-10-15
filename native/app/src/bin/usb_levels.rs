//! Raw level comparison: default is a hardware-free plan; --run is operator-only.
use anyhow::{ensure, Context, Result};
use nanoleaf_native::{config::Store, probe::levels};
use std::path::PathBuf;
fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let path = PathBuf::from(args.next().context("Usage: usb_levels CONFIG [--run]")?);
    let run = match args.next().as_deref() {
        None => false,
        Some(flag) if flag == "--run" => true,
        _ => anyhow::bail!("Usage: usb_levels CONFIG [--run]"),
    };
    ensure!(args.next().is_none(), "Unexpected extra argument");
    let store = Store::load(&path)?;
    if run {
        levels::run(&store)
    } else {
        println!("{}", serde_json::to_string_pretty(&levels::plan(&store)?)?);
        Ok(())
    }
}
