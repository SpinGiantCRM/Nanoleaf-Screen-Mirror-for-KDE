use anyhow::{bail, Context, Result};
use nanoleaf_native::{
    config::Store,
    service::{self, Control},
};
use std::path::PathBuf;
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let command = args.get(1).map(String::as_str).unwrap_or("--daemon");
    let path = args.get(2).map(PathBuf::from).unwrap_or_else(|| {
        PathBuf::from(std::env::var_os("XDG_CONFIG_HOME").unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
                .join(".config")
                .into_os_string()
        }))
        .join("nanoleaf-kde-sync/config.toml")
    });
    let duration =
        || -> Result<f64> { Ok(args.get(3).map(|s| s.parse()).transpose()?.unwrap_or(8.0)) };
    match command {
        "--install-launcher" => {
            println!("{}", nanoleaf_native::launcher::install()?.display());
            Ok(())
        }
        "--capture-probe" => nanoleaf_native::probe::capture(&path, duration()?),
        "--stream-capture-probe" => nanoleaf_native::probe::stream_capture(&path,duration()?),
        "--live-probe" => service::run_profile(&path, duration()?),
        "--stream-live-probe" => service::run_stream_profile(&path,duration()?),
        "--daemon" => service::run(&path, false, true),
        "--run" => service::run(&path, true, true),
        "--headless" => service::run(&path, false, false),
        "--start" | "--stop" | "--status" | "--reload" | "--quit" => {
            let action = match command {
                "--start" => Control::Start,
                "--stop" => Control::Stop,
                "--reload" => Control::Reload,
                "--quit" => Control::Quit,
                _ => Control::Status,
            };
            println!("{}", serde_json::to_string(&service::send(&action)?)?);
            Ok(())
        }
        "--preflight" => {
            let store = Store::load(&path).context("Native configuration preflight")?;
            let readiness = nanoleaf_native::pipeline::validate_mirroring(&store.config);
            println!("{}", serde_json::json!({
                "schema_version": store.config.schema_version,
                "manual_strip_zones": store.config.device_zone_count,
                "source_zones": store.config.zones.len(),
                "configuration_read_only": true,
                "colour_mapping_ready": readiness.is_ok(),
                "readiness_error": readiness.err().map(|e| e.to_string()),
                "rust": true
            }));
            Ok(())
        }
        #[cfg(feature = "gui")]
        "--settings" => nanoleaf_native::ui::open(&path),
        _ => bail!("Use --daemon, --run, --headless, --settings, --preflight, --start, --stop, --status, --reload, --quit, --install-launcher, --capture-probe, --stream-capture-probe, --live-probe or --stream-live-probe. Optional second argument: existing config path."),
    }
}
