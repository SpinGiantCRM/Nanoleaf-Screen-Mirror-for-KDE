use std::{fs, process::Command};

const FLAGS: [&str; 6] = [
    "--ack-path",
    "--ack-output",
    "--ack-control",
    "--ack-pacing",
    "--ack-brightness",
    "--ack-shape",
];

#[test]
fn ack_experiments_are_plan_only_without_run_and_reject_unverified_geometry() {
    let root = std::env::temp_dir().join(format!("nanoleaf-ack-plan-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let path = root.join("config.toml");
    let original = "schema_version=2\ndevice_zone_count=48\nunknown_field='preserve'\n";
    fs::write(&path, original).unwrap();
    for flag in FLAGS {
        let output = Command::new(env!("CARGO_BIN_EXE_usb_bench"))
            .arg(&path)
            .arg(flag)
            .env_remove("XDG_RUNTIME_DIR")
            .output()
            .unwrap();
        assert!(output.status.success(), "{flag}: {:?}", output.stderr);
        let plan: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(plan["manual_zones"], 48);
        assert_eq!(plan["daily_transport_changed"], false);
        assert!(plan["hardware_run_requires"]
            .as_str()
            .unwrap()
            .contains(flag));
        if flag == "--ack-shape" {
            assert_eq!(plan["transactions"], 384);
            assert_eq!(plan["samples_per_case"], 8);
            assert_eq!(plan["warmup_samples_per_case"], 2);
            assert_eq!(plan["shapes"].as_array().unwrap().len(), 4);
        }
        for args in [vec![flag, "extra"], vec![flag, "--run", "extra"]] {
            let output = Command::new(env!("CARGO_BIN_EXE_usb_bench"))
                .arg(&path)
                .args(args)
                .env_remove("XDG_RUNTIME_DIR")
                .output()
                .unwrap();
            assert!(!output.status.success());
            assert!(!String::from_utf8_lossy(&output.stderr).contains("desktop runtime"));
        }
    }
    assert_eq!(fs::read_to_string(&path).unwrap(), original);
    for invalid in [
        "device_zone_count=75",
        "device_zone_count=48\ndevice_pid=33281",
        "device_zone_count=48\ndevice_vid=1",
    ] {
        fs::write(&path, invalid).unwrap();
        for flag in FLAGS {
            let output = Command::new(env!("CARGO_BIN_EXE_usb_bench"))
                .arg(&path)
                .arg(flag)
                .env_remove("XDG_RUNTIME_DIR")
                .output()
                .unwrap();
            assert!(!output.status.success(), "{flag} accepted {invalid}");
        }
    }
    fs::remove_dir_all(root).unwrap();
}
