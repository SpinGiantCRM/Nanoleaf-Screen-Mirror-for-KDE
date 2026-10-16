use nanoleaf_native::package::{install, rollback, uninstall};
use sha2::{Digest, Sha256};
use std::{
    fs,
    os::unix::fs::symlink,
    path::{Path, PathBuf},
};
// CLI tests fork before exec. During that brief interval a child can inherit
// another test thread's advisory lock, despite CLOEXEC. Keep package fixtures
// serial so process launch cannot create a false install-lock contention.
static PACKAGE_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn fixture(name: &str) -> (PathBuf, PathBuf, PathBuf, PathBuf) {
    let root = std::env::temp_dir().join(format!("nanoleaf-package-{name}-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let bundle = root.join("bundle");
    fs::create_dir_all(bundle.join("bin")).unwrap();
    for name in [
        "bin/nanoleaf-native",
        "bin/nanoleaf-native-capture",
        "LICENSE",
        "README.md",
        "60-nanoleaf-kde-sync.rules",
    ] {
        fs::write(bundle.join(name), name).unwrap();
    }
    manifest(&bundle);
    let prefix = root.join("prefix with spaces");
    let data = root.join("data");
    (root, bundle, prefix, data)
}
fn manifest(bundle: &Path) {
    let mut content = String::new();
    for name in [
        "bin/nanoleaf-native",
        "bin/nanoleaf-native-capture",
        "LICENSE",
        "README.md",
        "60-nanoleaf-kde-sync.rules",
    ] {
        content.push_str(&format!(
            "{:x}  {name}\n",
            Sha256::digest(fs::read(bundle.join(name)).unwrap())
        ));
    }
    fs::write(bundle.join("SHA256SUMS"), content).unwrap();
}
#[test]
fn install_upgrade_and_two_way_rollback_preserve_unrelated_files_and_configuration() {
    let _guard = PACKAGE_TEST_LOCK.lock().unwrap();
    let (root, bundle, prefix, data) = fixture("upgrade");
    let config = root.join("calibration.toml");
    let unrelated = data.join("applications/example-unrelated.desktop");
    fs::create_dir_all(unrelated.parent().unwrap()).unwrap();
    fs::write(&unrelated, "unrelated launcher").unwrap();
    fs::write(&config, "measured gains and anchors").unwrap();
    let first = install(&bundle, &prefix, &data).unwrap();
    assert_eq!(install(&bundle, &prefix, &data).unwrap(), first);
    fs::write(bundle.join("bin/nanoleaf-native"), "updated app").unwrap();
    manifest(&bundle);
    let second = install(&bundle, &prefix, &data).unwrap();
    assert_ne!(first, second);
    assert_eq!(
        fs::read_link(prefix.join("bin/nanoleaf-native")).unwrap(),
        second.join("bin/nanoleaf-native")
    );
    assert_eq!(rollback(&prefix, &data).unwrap(), first);
    assert_eq!(rollback(&prefix, &data).unwrap(), second);
    assert_eq!(
        fs::read_to_string(config).unwrap(),
        "measured gains and anchors"
    );
    assert_eq!(fs::read_to_string(unrelated).unwrap(), "unrelated launcher");
    assert!(first.join("bin/nanoleaf-native-capture").is_file());
    uninstall(&prefix, &data).unwrap();
    assert!(!prefix.join("bin/nanoleaf-native").exists());
    assert!(first.join("bin/nanoleaf-native-capture").is_file());
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn corruption_and_symlinks_never_publish_a_bundle() {
    let _guard = PACKAGE_TEST_LOCK.lock().unwrap();
    let (root, bundle, prefix, data) = fixture("corruption");
    fs::write(bundle.join("bin/nanoleaf-native-capture"), "wrong helper").unwrap();
    assert!(install(&bundle, &prefix, &data).is_err());
    assert!(!prefix.exists());
    manifest(&bundle);
    fs::remove_file(bundle.join("LICENSE")).unwrap();
    symlink("README.md", bundle.join("LICENSE")).unwrap();
    assert!(install(&bundle, &prefix, &data).is_err());
    assert!(!prefix.exists());
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn external_edits_and_corrupt_rollback_version_are_refused() {
    let _guard = PACKAGE_TEST_LOCK.lock().unwrap();
    let (root, bundle, prefix, data) = fixture("external");
    let first = install(&bundle, &prefix, &data).unwrap();
    let entry = data.join("applications/org.spingiantcrm.NanoleafNative.desktop");
    let original = fs::read(&entry).unwrap();
    fs::write(&entry, "external edit").unwrap();
    assert!(install(&bundle, &prefix, &data).is_err());
    assert_eq!(fs::read_to_string(&entry).unwrap(), "external edit");
    fs::write(&entry, original).unwrap();
    fs::write(bundle.join("README.md"), "new version").unwrap();
    manifest(&bundle);
    install(&bundle, &prefix, &data).unwrap();
    fs::write(
        first.join("bin/nanoleaf-native-capture"),
        "corrupt previous helper",
    )
    .unwrap();
    let before = fs::read(&entry).unwrap();
    assert!(rollback(&prefix, &data).is_err());
    assert_eq!(fs::read(&entry).unwrap(), before);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn notice_manifest_upgrades_and_rolls_back_to_the_earlier_bundle_format() {
    let _guard = PACKAGE_TEST_LOCK.lock().unwrap();
    let (root, bundle, prefix, data) = fixture("notices");
    let legacy = install(&bundle, &prefix, &data).unwrap();
    let notice = b"Published dependency licence notices";
    fs::write(bundle.join("THIRD_PARTY_NOTICES.txt"), notice).unwrap();
    let mut sum = fs::read_to_string(bundle.join("SHA256SUMS")).unwrap();
    sum.push_str(&format!(
        "{:x}  THIRD_PARTY_NOTICES.txt\n",
        Sha256::digest(notice)
    ));
    fs::write(bundle.join("SHA256SUMS"), sum).unwrap();
    let next = install(&bundle, &prefix, &data).unwrap();
    assert_ne!(next, legacy);
    assert_eq!(
        fs::read(next.join("THIRD_PARTY_NOTICES.txt")).unwrap(),
        notice
    );
    assert_eq!(rollback(&prefix, &data).unwrap(), legacy);
    assert_eq!(rollback(&prefix, &data).unwrap(), next);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn disabling_autostart_needs_no_installed_launcher_and_preserves_foreign_files() {
    let _guard = PACKAGE_TEST_LOCK.lock().unwrap();
    let (root, _bundle, _prefix, data) = fixture("autostart-off");
    let config = root.join("config");
    fs::create_dir_all(config.join("autostart")).unwrap();
    let entry = config.join("autostart/org.spingiantcrm.NanoleafNative.desktop");
    let run = || {
        std::process::Command::new(env!("CARGO_BIN_EXE_nanoleaf-native"))
            .args(["--autostart", "off"])
            .env("HOME", &root)
            .env("XDG_CONFIG_HOME", &config)
            .env("XDG_DATA_HOME", &data)
            .output()
            .unwrap()
    };
    fs::write(&entry, "# Managed by nanoleaf-native\nold entry").unwrap();
    assert!(run().status.success());
    assert!(!entry.exists());
    assert!(run().status.success());
    fs::write(&entry, "user-managed entry").unwrap();
    assert!(!run().status.success());
    assert_eq!(fs::read_to_string(&entry).unwrap(), "user-managed entry");
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn refused_uninstall_does_not_disable_autostart() {
    let _guard = PACKAGE_TEST_LOCK.lock().unwrap();
    let (root, bundle, prefix, data) = fixture("uninstall-refusal");
    install(&bundle, &prefix, &data).unwrap();
    let config = root.join("config");
    let runtime = root.join("runtime");
    fs::create_dir_all(config.join("autostart")).unwrap();
    fs::create_dir(&runtime).unwrap();
    let startup = config.join("autostart/org.spingiantcrm.NanoleafNative.desktop");
    let original = "# Managed by nanoleaf-native\nkeep this entry";
    fs::write(&startup, original).unwrap();
    fs::write(
        data.join("applications/org.spingiantcrm.NanoleafNative.desktop"),
        "external edit",
    )
    .unwrap();
    let result = std::process::Command::new(env!("CARGO_BIN_EXE_nanoleaf-native"))
        .arg("--uninstall-native")
        .arg(&prefix)
        .env("HOME", &root)
        .env("XDG_CONFIG_HOME", &config)
        .env("XDG_DATA_HOME", &data)
        .env("XDG_RUNTIME_DIR", &runtime)
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert_eq!(fs::read_to_string(&startup).unwrap(), original);
    assert!(prefix.join("bin/nanoleaf-native").exists());
    fs::remove_dir_all(root).unwrap();
}
