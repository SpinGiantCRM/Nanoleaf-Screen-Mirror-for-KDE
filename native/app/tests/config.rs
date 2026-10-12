use nanoleaf_native::config::Store;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

static SEQUENCE: AtomicU64 = AtomicU64::new(0);
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
