use anyhow::{Context, Result};
use nanoleaf_native::config::Store;
use std::path::PathBuf;

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let path = args.get(2).map(PathBuf::from).unwrap_or_else(|| {
        PathBuf::from(std::env::var_os("XDG_CONFIG_HOME").unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                .join(".config")
                .into_os_string()
        }))
        .join("nanoleaf-kde-sync/config.toml")
    });
    let store = Store::load(&path).context("Native configuration preflight")?;
    #[cfg(feature = "gui")]
    if args.get(1).is_some_and(|arg| arg == "--settings") {
        return nanoleaf_native::ui::open(&path);
    }
    println!(
        "{}",
        serde_json::json!({"schema_version":store.config.schema_version,
        "manual_strip_zones":store.config.device_zone_count,"source_zones":store.config.zones.len(),
        "configuration_read_only":true,"rust":true})
    );
    Ok(())
}
