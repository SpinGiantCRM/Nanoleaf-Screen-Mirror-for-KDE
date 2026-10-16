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
    if matches!(command, "--daemon" | "--run" | "--headless" | "--settings") {
        Store::initialize(&path)?;
    }
    match command {
        "--version" => { println!("nanoleaf-native {}", env!("CARGO_PKG_VERSION")); Ok(()) }
        "--fast-response" => {
            let mut store = Store::load(&path)?;
            store.save_fast_response()?;
            println!("{}", serde_json::json!({"settings_saved":true,"smoothing":store.config.smoothing,"zone_temporal_accumulation":store.config.zone_temporal_accumulation,"runtime_changed":false,"next_step":"Reload or restart mirroring to use the saved settings; the original configuration backup is retained."}));
            Ok(())
        }
        "--capture-backend" => {
            let backend = args.get(3).context("Use --capture-backend EXISTING_CONFIG auto|kwin-dbus|xdg-portal")?;
            let mut store = Store::load(&path)?;
            store.save_capture_backend(backend)?;
            println!("{}", serde_json::json!({"settings_saved":true,"capture_backend":store.config.capture_backend,"runtime_changed":false,"next_step":"Reload or restart mirroring to use the saved backend; the exact configuration backup is retained."}));
            Ok(())
        }
        "--install-native" | "--rollback-native" | "--uninstall-native" => {
            let _maintenance = service::Paths::new()?.maintenance()?;
            let prefix = args.get(2).map(PathBuf::from).unwrap_or(PathBuf::from(std::env::var_os("HOME").context("Home directory")?).join(".local"));
            let data = nanoleaf_native::package::user_data()?;
            if command == "--uninstall-native" {
                nanoleaf_native::package::uninstall(&prefix, &data)?;
                nanoleaf_native::package::autostart(false)?;
                nanoleaf_native::package::refresh_desktop()?;
                println!("Native command removed; versions and calibration are retained.");
                return Ok(());
            }
            let installed = if command == "--install-native" {
                let exe = std::env::current_exe()?.canonicalize()?;
                let bundle = exe.parent().and_then(std::path::Path::parent).context("Bundle directory")?;
                nanoleaf_native::package::install(bundle, &prefix, &data)?
            } else { nanoleaf_native::package::rollback(&prefix, &data)? };
            nanoleaf_native::package::refresh_desktop()?;
            println!("Installed {}. Your configuration and calibration are unchanged.", installed.display()); Ok(())
        }
        "--autostart" => {
            let enable = match args.get(2).map(String::as_str) { Some("on") => true, Some("off") => false, _ => bail!("Use --autostart on or --autostart off") };
            nanoleaf_native::package::autostart(enable)?; Ok(())
        }
        "--doctor" => {
            let config = Store::load(&path);
            let ready = config.as_ref().ok().map(|s|nanoleaf_native::pipeline::validate_mirroring(&s.config));
            let hid = hidapi::HidApi::new()?;
            let strips:Vec<_> = hid.device_list().filter(|d| nanoleaf_core::protocol::supports_usb(d.vendor_id(),d.product_id())).map(|d|serde_json::json!({"vid":d.vendor_id(),"pid":d.product_id(),"interface":d.interface_number()})).collect();
            let helper = std::env::current_exe()?.parent().context("Executable directory")?.join("nanoleaf-native-capture");
            println!("{}",serde_json::json!({"configuration_read_only":true,"configuration_error":config.as_ref().err().map(ToString::to_string),"mirroring_ready":ready.as_ref().is_some_and(|r|r.is_ok()),"readiness_error":ready.and_then(|r|r.err()).map(|e|e.to_string()),"usb_devices_detected":strips,"usb_output_tested":false,"stream_helper_present":helper.is_file(),"wayland_session":std::env::var_os("WAYLAND_DISPLAY").is_some(),"privileged_access_required":false})); Ok(())
        }
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
        _ => bail!("Use --version, --doctor, --fast-response, --capture-backend EXISTING_CONFIG BACKEND, --install-native, --rollback-native, --uninstall-native, --autostart on/off, --daemon, --run, --headless, --settings, --preflight, --start, --stop, --status, --reload, --quit, --install-launcher, --capture-probe, --stream-capture-probe, --live-probe or --stream-live-probe. Optional second argument: existing config path."),
    }
}
