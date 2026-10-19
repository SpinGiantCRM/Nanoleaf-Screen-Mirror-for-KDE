//! Raw level comparison: default is a hardware-free plan; --run is operator-only.
use anyhow::{ensure, Context, Result};
use nanoleaf_native::{config::Store, probe::levels};
use std::path::PathBuf;
fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let path = PathBuf::from(
        args.next()
            .context("Usage: usb_levels CONFIG [--level 0|15|16|24] [--run]")?,
    );
    let mut run = false;
    let mut level = None;
    while let Some(arg) = args.next() {
        if arg == "--run" {
            ensure!(!run, "Repeated --run");
            run = true;
        } else if arg == "--level" {
            ensure!(level.is_none(), "Repeated --level");
            level = Some(
                args.next()
                    .context("Missing raw code")?
                    .to_str()
                    .context("Invalid raw code")?
                    .parse::<u8>()?,
            );
        } else {
            anyhow::bail!("Use --level 0|15|16|24 and/or --run");
        }
    }
    let store = Store::load(&path)?;
    match (run, level) {
        (true, Some(level)) => levels::run_single(&store, level),
        (true, None) => levels::run(&store),
        (false, level) => {
            let plan = match level {
                Some(level) => levels::single_plan(&store, level)?,
                None => levels::plan(&store)?,
            };
            println!("{}", serde_json::to_string_pretty(&plan)?);
            Ok(())
        }
    }
}
