use nanoleaf_native::package::{install, rollback, uninstall};
use sha2::{Digest, Sha256};
use std::{
    fs,
    os::unix::fs::symlink,
    path::{Path, PathBuf},
};
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
fn install_upgrade_and_two_way_rollback_preserve_fallback_and_configuration() {
    let (root, bundle, prefix, data) = fixture("upgrade");
    let config = root.join("calibration.toml");
    let fallback = data.join("applications/nanoleaf-kde-sync.desktop");
    fs::create_dir_all(fallback.parent().unwrap()).unwrap();
    fs::write(&fallback, "Python fallback").unwrap();
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
    assert_eq!(fs::read_to_string(fallback).unwrap(), "Python fallback");
    assert!(first.join("bin/nanoleaf-native-capture").is_file());
    uninstall(&prefix, &data).unwrap();
    assert!(!prefix.join("bin/nanoleaf-native").exists());
    assert!(first.join("bin/nanoleaf-native-capture").is_file());
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn corruption_and_symlinks_never_publish_a_bundle() {
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
