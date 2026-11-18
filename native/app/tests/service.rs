use nanoleaf_native::service::{send_at, Control};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

struct ServiceChild(std::process::Child);
impl std::ops::Deref for ServiceChild {
    type Target = std::process::Child;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}
impl std::ops::DerefMut for ServiceChild {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}
impl Drop for ServiceChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}
#[test]
fn stopped_service_controls_never_open_capture_or_usb_and_keep_configuration_exact() {
    let root = std::env::temp_dir().join(format!("nanoleaf-service-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
    let config = root.join("config.toml");
    let original="schema_version=2\ndevice_zone_count=48\nstart_on_launch=false\nunknown_setting='preserved'\n";
    fs::write(&config, original).unwrap();
    let mut child = ServiceChild(
        Command::new(env!("CARGO_BIN_EXE_nanoleaf-native"))
            .arg("--headless")
            .arg(&config)
            .env("XDG_RUNTIME_DIR", &root)
            .env("XDG_STATE_HOME", root.join("state"))
            .env(
                "DBUS_SESSION_BUS_ADDRESS",
                format!("unix:path={}/missing.sock", root.display()),
            )
            .env(
                "DBUS_SYSTEM_BUS_ADDRESS",
                format!("unix:path={}/missing.sock", root.display()),
            )
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let socket = root.join("nanoleaf-native/control.sock");
    let deadline = Instant::now() + Duration::from_secs(3);
    while !socket.exists() && Instant::now() < deadline {
        if child.try_wait().unwrap().is_some() {
            panic!("Service exited before control listener became ready");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let s = send_at(&socket, &Control::Status).unwrap();
    assert!(!s.running);
    assert_eq!(s.frames, 0);
    assert_eq!(s.manual_zones, 48);
    let report = nanoleaf_native::service::request_report_at(&socket).unwrap();
    let report = serde_json::to_value(report).unwrap();
    assert_eq!(report["current"]["running"], false);
    assert_eq!(report["current"]["frames"], 0);
    let exported = Command::new(env!("CARGO_BIN_EXE_nanoleaf-native"))
        .arg("--save-report")
        .env("XDG_RUNTIME_DIR", &root)
        .env("XDG_STATE_HOME", root.join("state"))
        .output()
        .unwrap();
    assert!(exported.status.success(), "{exported:?}");
    let report_path = std::path::PathBuf::from(String::from_utf8(exported.stdout).unwrap().trim());
    assert!(report_path.starts_with(root.join("state")));
    let report_text = fs::read_to_string(&report_path).unwrap();
    assert!(!report_text.contains("unknown_setting"));
    assert!(!report_text.contains(config.to_str().unwrap()));
    assert_eq!(
        fs::metadata(&report_path).unwrap().permissions().mode() & 0o777,
        0o600
    );
    send_at(&socket, &Control::Start).unwrap();
    std::thread::sleep(Duration::from_millis(20));
    let s = send_at(&socket, &Control::Status).unwrap();
    assert!(!s.running && s.reconnects == 0);
    assert!(s.message.contains("corner anchors"));
    send_at(&socket, &Control::Stop).unwrap();
    send_at(
        &socket,
        &Control::Preview {
            rgb: [80; 3],
            zone: Some(999),
        },
    )
    .unwrap();
    std::thread::sleep(Duration::from_millis(20));
    let s = send_at(&socket, &Control::Status).unwrap();
    assert!(!s.running && !s.preview);
    assert_eq!(s.frames, 0);
    assert!(s.message.contains("manual strip count"));
    send_at(
        &socket,
        &Control::Preview {
            rgb: [80; 3],
            zone: None,
        },
    )
    .unwrap();
    std::thread::sleep(Duration::from_millis(20));
    let s = send_at(&socket, &Control::Status).unwrap();
    assert!(!s.running && !s.preview && s.reconnects == 0);
    assert!(s.message.contains("monitoring unavailable"));
    send_at(&socket, &Control::Quit).unwrap();
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            panic!("Quit timed out");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    assert_eq!(fs::read_to_string(&config).unwrap(), original);
    assert!(!socket.exists());
    // A later export must work after a full service exit and label its source
    // as cached rather than suggesting that mirroring is still running.
    let cached = report_path
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("latest-session.json");
    fs::write(&cached, report_text).unwrap();
    fs::set_permissions(&cached, fs::Permissions::from_mode(0o600)).unwrap();
    let exported = Command::new(env!("CARGO_BIN_EXE_nanoleaf-native"))
        .arg("--save-report")
        .env("XDG_RUNTIME_DIR", &root)
        .env("XDG_STATE_HOME", root.join("state"))
        .output()
        .unwrap();
    assert!(exported.status.success(), "{exported:?}");
    let saved = fs::read_to_string(String::from_utf8(exported.stdout).unwrap().trim()).unwrap();
    let saved: serde_json::Value = serde_json::from_str(&saved).unwrap();
    assert_eq!(saved["source"], "cached_session");
    assert_eq!(saved["stale"], true);
    assert_eq!(fs::read_to_string(&config).unwrap(), original);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn capture_watchdog_allows_permission_then_expires_stalls_and_resets_on_recovery() {
    use nanoleaf_native::service::CaptureWatchdog;
    let now = Instant::now();
    let mut w = CaptureWatchdog::default();
    assert!(!w.expired(now));
    w.start(now, 60);
    assert!(!w.expired(now + Duration::from_secs(119)));
    assert!(w.expired(now + Duration::from_secs(120)));
    w.frame(now);
    assert!(!w.expired(now + Duration::from_millis(1999)));
    assert!(w.expired(now + Duration::from_secs(2)));
    w.reset();
    assert_eq!(w.deadline(), None);
    w.start(now, 1);
    w.frame(now);
    assert!(!w.expired(now + Duration::from_millis(2999)));
    assert!(w.expired(now + Duration::from_secs(3)));
}

#[test]
fn maintenance_recovers_a_crash_socket_but_never_interrupts_a_live_service() {
    use nanoleaf_native::service::Paths;
    use std::os::unix::net::UnixListener;
    let root = std::env::temp_dir().join(format!("nanoleaf-maintenance-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let paths = Paths {
        socket: root.join("control.sock"),
        root: root.clone(),
    };
    let socket = UnixListener::bind(&paths.socket).unwrap();
    drop(socket);
    let guard = paths.maintenance().unwrap();
    assert!(!paths.socket.exists());
    assert!(paths.maintenance().is_err());
    drop(guard);
    fs::write(&paths.socket, "unrelated file").unwrap();
    assert!(paths.maintenance().is_err());
    assert_eq!(fs::read_to_string(&paths.socket).unwrap(), "unrelated file");
    fs::remove_dir_all(root).unwrap();
}
