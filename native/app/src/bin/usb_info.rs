//! Operator-only read-only identity probe. No DFU/reset/erase/write commands.
use anyhow::{Context, Result};
use nanoleaf_native::{config::Store, probe};
use std::path::PathBuf;
fn main() -> Result<()> {
    let path = PathBuf::from(
        std::env::args_os()
            .nth(1)
            .context("Existing config required; stop mirroring first")?,
    );
    probe::usb_information(&Store::load(&path)?)
}
