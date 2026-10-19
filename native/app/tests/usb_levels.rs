use std::{fs, process::Command};
#[test]
fn single_level_defaults_to_a_bounded_plan_and_rejects_unreviewed_codes_before_hid() {
    let root = std::env::temp_dir().join(format!("nanoleaf-level-plan-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let config = root.join("config.toml");
    let original = "schema_version=2\ndevice_zone_count=48\nunknown_field='keep'\n";
    fs::write(&config, original).unwrap();
    for level in [0, 15, 16, 24] {
        let output = Command::new(env!("CARGO_BIN_EXE_usb_levels"))
            .arg(&config)
            .args(["--level", &level.to_string()])
            .env_remove("XDG_RUNTIME_DIR")
            .output()
            .unwrap();
        assert!(output.status.success());
        let plan: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(plan["raw_levels"], serde_json::json!([level]));
        assert_eq!(plan["nominal_seconds"], 10);
        assert_eq!(plan["manual_zones"], 48);
        assert_eq!(plan["test_controller_brightness"], 10);
    }
    for args in [
        vec!["--level", "255", "--run"],
        vec!["--level"],
        vec!["--level", "16", "--level", "0"],
        vec!["--run", "--run"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_usb_levels"))
            .arg(&config)
            .args(args)
            .env_remove("XDG_RUNTIME_DIR")
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(!String::from_utf8_lossy(&output.stderr).contains("desktop runtime"));
    }
    assert_eq!(fs::read_to_string(&config).unwrap(), original);
    fs::remove_dir_all(root).unwrap();
}
