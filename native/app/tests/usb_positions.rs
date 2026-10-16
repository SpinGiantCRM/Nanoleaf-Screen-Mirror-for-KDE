use std::{fs, process::Command};

#[test]
fn position_plan_never_opens_hid_and_rejects_unknown_or_extra_arguments() {
    let root = std::env::temp_dir().join(format!("nanoleaf-position-plan-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let path = root.join("config.toml");
    let original = "schema_version=2\ndevice_zone_count=48\nunknown_field='preserve'\n";
    fs::write(&path, original).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_usb_bench"))
        .arg(&path)
        .arg("--positions")
        .env_remove("XDG_RUNTIME_DIR")
        .output()
        .unwrap();
    assert!(output.status.success());
    let plan: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(plan["manual_zones"], 48);
    assert_eq!(plan["test_transactions"], 512);
    let output = Command::new(env!("CARGO_BIN_EXE_usb_bench"))
        .arg(&path)
        .arg("--repeat-response")
        .env_remove("XDG_RUNTIME_DIR")
        .output()
        .unwrap();
    assert!(output.status.success());
    let plan: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(plan["trials"], 32);
    assert_eq!(plan["manual_zones"], 48);
    for args in [
        ["--positions", "unexpected"],
        ["--positions", "--content"],
        ["--run", "--positions"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_usb_bench"))
            .arg(&path)
            .args(args)
            .env_remove("XDG_RUNTIME_DIR")
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(!String::from_utf8_lossy(&output.stderr).contains("desktop runtime"));
    }
    assert_eq!(fs::read_to_string(&path).unwrap(), original);
    fs::remove_dir_all(root).unwrap();
}
