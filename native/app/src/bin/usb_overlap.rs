//! Operator-only two-outstanding USB experiment. Not shipped as daily transport.
use anyhow::{Context, Result};
use nanoleaf_native::{config::Store, device::overlap};
use std::path::PathBuf;
fn main() -> Result<()> {
    let path = PathBuf::from(
        std::env::args_os()
            .nth(1)
            .context("Existing config required; stop mirroring first")?,
    );
    let gap = std::env::args()
        .nth(2)
        .map(|arg| arg.parse::<f64>())
        .transpose()?;
    let train = match std::env::args().nth(3).as_deref() {
        None => false,
        Some("--train") => true,
        _ => anyhow::bail!("Use usb_overlap CONFIG [SOURCE_GAP_MS [--train]]"),
    };
    overlap::probe(&Store::load(&path)?, gap, train)
}
