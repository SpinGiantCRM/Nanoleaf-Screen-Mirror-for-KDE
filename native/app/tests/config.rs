use nanoleaf_native::config::Store;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[test]
fn fast_response_changes_only_existing_temporal_controls() {
    let mut config = nanoleaf_native::config::Config {
        device_zone_count: 48,
        fps: 120,
        ..Default::default()
    };
    config.led_calibration_profile_sdr.red_gain = 0.42;
    config.led_calibration_profile_hdr.led_gamma = 1.9;
    let mut expected = serde_json::to_value(&config).unwrap();
    expected["smoothing"] = serde_json::json!(1.0);
    expected["zone_temporal_accumulation"] = serde_json::json!(false);
    config.enable_fast_response();
    assert_eq!(serde_json::to_value(&config).unwrap(), expected);
}

#[test]
fn saved_fast_response_keeps_profiles_unknowns_comments_and_exact_backup() {
    let text="# personal config\nschema_version=2\ndevice_zone_count=48\nfps=60\nsmoothing=0.5 # response\nfuture_option='preserved'\n[led_calibration_profile_sdr]\nred_gain=0.42 # measured gain\nled_gamma=0.7\n[led_calibration_profile_hdr]\nred_gain=0.91\nled_gamma=1.8\n";
    let f = Fixture::new(text);
    let mut store = Store::load(&f.file).unwrap();
    let mut expected = serde_json::to_value(&store.config).unwrap();
    expected["smoothing"] = serde_json::json!(1.0);
    expected["zone_temporal_accumulation"] = serde_json::json!(false);
    store.save_fast_response().unwrap();
    assert_eq!(serde_json::to_value(&store.config).unwrap(), expected);
    let saved = fs::read_to_string(&f.file).unwrap();
    assert!(saved.contains("# personal config"));
    assert!(saved.contains("# response"));
    assert!(saved.contains("red_gain=0.42 # measured gain"));
    assert!(saved.contains("future_option='preserved'"));
    let backups: Vec<_> = fs::read_dir(&f.root)
        .unwrap()
        .filter_map(|x| {
            let p = x.unwrap().path();
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .contains("native-backup")
                .then_some(p)
        })
        .collect();
    assert_eq!(backups.len(), 1);
    assert_eq!(fs::read(&backups[0]).unwrap(), text.as_bytes());
    store.save_fast_response().unwrap();
    assert_eq!(
        fs::read_dir(&f.root)
            .unwrap()
            .filter(|x| x
                .as_ref()
                .unwrap()
                .file_name()
                .to_string_lossy()
                .contains("native-backup"))
            .count(),
        1
    );
}
struct Fixture {
    root: PathBuf,
    file: PathBuf,
}
impl Fixture {
    fn new(text: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "nanoleaf-config-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let file = root.join("config.toml");
        fs::write(&file, text).unwrap();
        Self { root, file }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn legacy_load_migrates_only_in_memory_and_keeps_gains() {
    let text="# personal calibration\nschema_version=1\ndevice_zone_count=48\nred_gain=0.87\ncorner_anchor_top_left=2\nunknown_setting='keep me'\n";
    let f = Fixture::new(text);
    let store = Store::load(&f.file).unwrap();
    assert_eq!(store.config.schema_version, 2);
    assert_eq!(store.config.device_zone_count, 48);
    assert_eq!(store.config.led_calibration_profile_sdr.red_gain, 0.87);
    assert_eq!(store.config.calibration.corner_anchor_top_left, 2);
    assert_eq!(fs::read_to_string(&f.file).unwrap(), text);
    assert_eq!(fs::read_dir(&f.root).unwrap().count(), 1);
}

#[test]
fn transactional_edit_preserves_unknown_fields_and_exact_backup() {
    let text="# preserve comment\nschema_version=2\ndevice_zone_count=48\nbrightness=0.9\nunknown_setting='keep me'\n[calibration]\ndevice_zone_count=48\ncorner_anchor_top_left=2\nprivate_future_flag=true\n";
    let f = Fixture::new(text);
    let mut store = Store::load(&f.file).unwrap();
    let doc = store
        .update_scalar("brightness", toml_edit::Value::from(0.75))
        .unwrap();
    store.save_document(doc).unwrap();
    let saved = fs::read_to_string(&f.file).unwrap();
    assert!(saved.contains("# preserve comment"));
    assert!(saved.contains("unknown_setting='keep me'"));
    assert!(saved.contains("private_future_flag=true"));
    assert_eq!(store.config.calibration.corner_anchor_top_left, 2);
    let backups: Vec<_> = fs::read_dir(&f.root)
        .unwrap()
        .filter_map(|p| {
            let p = p.unwrap().path();
            p.file_name()
                .unwrap()
                .to_str()
                .unwrap()
                .contains("native-backup")
                .then_some(p)
        })
        .collect();
    assert_eq!(backups.len(), 1);
    assert_eq!(fs::read(&backups[0]).unwrap(), text.as_bytes());
}

#[test]
fn stale_write_is_rejected_without_overwriting_external_change() {
    let f = Fixture::new("schema_version=2\ndevice_zone_count=48\n");
    let mut store = Store::load(&f.file).unwrap();
    fs::write(&f.file, "device_zone_count=24\n").unwrap();
    let doc = store
        .update_scalar("brightness", toml_edit::Value::from(0.5))
        .unwrap();
    assert!(store.save_document(doc).is_err());
    assert_eq!(
        fs::read_to_string(&f.file).unwrap(),
        "device_zone_count=24\n"
    );
}

#[test]
fn future_schemas_nan_profiles_and_invalid_manual_counts_are_rejected() {
    for text in [
        "schema_version=3\n",
        "device_zone_count=513\n",
        "red_gain=nan\n",
        "[calibration]\ncalibration_schema_version=2\n",
    ] {
        let f = Fixture::new(text);
        assert!(Store::load(&f.file).is_err(), "{text}");
        assert_eq!(fs::read_to_string(&f.file).unwrap(), text);
    }
}

#[test]
fn no_op_save_does_not_create_backup_or_touch_bytes() {
    let text = "schema_version=2\ndevice_zone_count=48\n";
    let f = Fixture::new(text);
    let mut store = Store::load(&f.file).unwrap();
    store.save_document(store.document.clone()).unwrap();
    assert_eq!(fs::read_dir(&f.root).unwrap().count(), 1);
    assert_eq!(fs::read_to_string(&f.file).unwrap(), text);
}

#[test]
fn source_count_overflow_and_unknown_colour_policy_fail_read_only() {
    for text in [
        "device_zone_count=48\nsource_side_counts=[9223372036854775807,9223372036854775807,1,1]\n",
        "device_zone_count=48\ncolor_style='unknown-new-policy'\n",
    ] {
        let f = Fixture::new(text);
        assert!(Store::load(&f.file).is_err());
        assert_eq!(fs::read_to_string(&f.file).unwrap(), text);
    }
}
#[test]
fn legacy_enum_case_normalizes_only_in_memory() {
    let text="schema_version=1\ndevice_zone_count=48\noutput_channel_order='RGB'\ncolor_style='REFERENCE'\n";
    let f = Fixture::new(text);
    let s = Store::load(&f.file).unwrap();
    assert_eq!(s.config.output_channel_order, "rgb");
    assert_eq!(s.config.color_style, "reference");
    assert_eq!(fs::read_to_string(&f.file).unwrap(), text);
}

#[test]
fn first_launch_initializes_only_absent_configuration_and_is_safe_for_existing_bytes() {
    let root = std::env::temp_dir().join(format!("nanoleaf-init-{}", std::process::id()));
    let path = root.join("config.toml");
    nanoleaf_native::config::Store::initialize(&path).unwrap();
    let store = nanoleaf_native::config::Store::load(&path).unwrap();
    assert_eq!(store.config.device_zone_count, 0);
    assert!(!store.config.start_on_launch);
    std::fs::write(&path, "calibration to preserve exactly").unwrap();
    nanoleaf_native::config::Store::initialize(&path).unwrap();
    assert_eq!(
        std::fs::read_to_string(&path).unwrap(),
        "calibration to preserve exactly"
    );
    std::fs::remove_dir_all(root).unwrap();
}
