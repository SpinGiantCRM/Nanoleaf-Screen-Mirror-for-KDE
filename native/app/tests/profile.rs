use nanoleaf_native::{config::LedProfile, profile};
use std::{
    fs,
    os::unix::fs::{symlink, PermissionsExt},
};
#[test]
fn profile_round_trip_preserves_exact_calibration_and_legacy_schema() {
    let p = LedProfile {
        red_gain: 0.873123456789,
        led_gamma: 0.7,
        color_matrix: vec![1.0, 0.02, 0.0, 0.01, 0.98, 0.01, 0.0, 0.02, 1.0],
        ..Default::default()
    };
    for preset in ["sdr", "hdr"] {
        let raw = profile::encode(preset, &p).unwrap();
        let (kind, parsed) = profile::decode(&raw).unwrap();
        assert_eq!(kind, preset);
        assert_eq!(
            serde_json::to_value(parsed).unwrap(),
            serde_json::to_value(&p).unwrap()
        );
        let json: serde_json::Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(
            json["profile"]["profile_kind"],
            "nanoleaf-kde-sync-led-calibration-profile"
        );
        assert_eq!(json["profile"]["schema_version"], 1);
    }
    let invalid = profile::encode("future-transfer", &p);
    assert!(invalid.is_err());
    let raw = profile::encode("sdr", &p).unwrap();
    assert!(
        profile::decode(&raw.replace("\"schema_version\": 1", "\"schema_version\": 2")).is_err()
    );
    assert!(profile::decode(&raw.replace("\"led_gamma\": 0.7", "\"led_gamma\": 1e400")).is_err());
}
#[test]
fn export_is_private_atomic_backed_up_and_refuses_symlinks() {
    let root = std::env::temp_dir().join(format!("nanoleaf-profile-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let file = root.join("measured.json");
    let p = LedProfile::default();
    assert!(profile::export(&file, "sdr", &p).unwrap().is_none());
    let original = fs::read(&file).unwrap();
    assert_eq!(
        fs::metadata(&file).unwrap().permissions().mode() & 0o777,
        0o600
    );
    let changed = LedProfile {
        red_gain: 0.89,
        ..p
    };
    let backup = profile::export(&file, "sdr", &changed).unwrap().unwrap();
    assert_eq!(fs::read(backup).unwrap(), original);
    assert_eq!(profile::load(&file).unwrap().1.red_gain, 0.89);
    let link = root.join("link.json");
    symlink(root.join("absent.json"), &link).unwrap();
    assert!(profile::export(&link, "sdr", &changed).is_err());
    assert!(fs::symlink_metadata(link).unwrap().file_type().is_symlink());
    assert!(profile::export(&root.join("config.toml"), "sdr", &changed).is_err());
    fs::remove_dir_all(root).unwrap();
}
