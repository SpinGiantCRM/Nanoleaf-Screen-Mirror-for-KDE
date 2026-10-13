//! Independent, unprivileged native bundle installation. Configuration and the
//! Python package are never written. Versions remain available for rollback.
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::fs::{symlink, OpenOptionsExt},
    path::{Path, PathBuf},
};
const FILES: [&str; 5] = [
    "bin/nanoleaf-native",
    "bin/nanoleaf-native-capture",
    "LICENSE",
    "README.md",
    "60-nanoleaf-kde-sync.rules",
];
#[derive(Serialize, Deserialize)]
struct State {
    current: String,
    previous: Option<String>,
    launcher: String,
    original_launcher: Option<String>,
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn regular(path: &Path) -> Result<Vec<u8>> {
    ensure!(
        fs::symlink_metadata(path)?.file_type().is_file(),
        "Expected a regular file: {}",
        path.display()
    );
    Ok(fs::read(path)?)
}
fn directory(path: &Path) -> Result<()> {
    fs::create_dir_all(path)?;
    ensure!(
        fs::symlink_metadata(path)?.file_type().is_dir(),
        "Unsafe installation directory: {}",
        path.display()
    );
    Ok(())
}
fn atomic(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let tmp = path.with_extension(format!("native-{}.tmp", std::process::id()));
    let result = (|| {
        let mut f = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(mode)
            .open(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
        fs::rename(&tmp, path)?;
        File::open(path.parent().context("File parent")?)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(tmp);
    }
    result
}
fn desktop(exe: &Path) -> Result<String> {
    let exec = exe.to_str().context("Non-UTF8 executable path")?;
    ensure!(
        !exec
            .chars()
            .any(|c| c.is_control() || matches!(c, '"' | '\\' | '`' | '$' | '%')),
        "Unsupported desktop executable path"
    );
    Ok(format!("[Desktop Entry]\nType=Application\nVersion=1.0\nName=Nanoleaf Screen Mirror (Rust)\nComment=Native single-strip screen mirror\nExec=\"{exec}\" --daemon\nTryExec={exec}\nIcon=preferences-desktop-color\nTerminal=false\nCategories=Utility;\nStartupNotify=false\nX-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n"))
}
fn version_path(root: &Path, id: &str) -> Result<PathBuf> {
    ensure!(
        id.len() == 64 && id.bytes().all(|b| b.is_ascii_hexdigit()),
        "Invalid installed version identifier"
    );
    Ok(root.join(id))
}
fn link(path: &Path, target: &Path) -> Result<()> {
    let tmp = path.with_extension(format!("native-{}.tmp", std::process::id()));
    symlink(target, &tmp)?;
    let result = fs::rename(&tmp, path);
    if result.is_err() {
        let _ = fs::remove_file(tmp);
    }
    result?;
    Ok(())
}
/// Data directory supplied explicitly so packaging tests cannot touch the desktop.
/// Returns the immutable version directory; no service or LED activity is started.
pub fn install(bundle: &Path, prefix: &Path, data: &Path) -> Result<PathBuf> {
    let manifest = regular(&bundle.join("SHA256SUMS"))?;
    let manifest_text = std::str::from_utf8(&manifest)?;
    let lines: Vec<_> = manifest_text.lines().collect();
    ensure!(
        lines.len() == FILES.len() || lines.len() == FILES.len() + 1,
        "Incomplete bundle manifest"
    );
    let mut files = Vec::new();
    for name in FILES {
        let bytes = regular(&bundle.join(name))?;
        let expected = format!("{}  {name}", digest(&bytes));
        ensure!(
            lines.iter().filter(|l| **l == expected).count() == 1,
            "Bundle checksum mismatch: {name}"
        );
        ensure!(!bytes.is_empty(), "Empty bundle file: {name}");
        files.push((name, bytes));
    }
    if lines.len() == FILES.len() + 1 {
        let name = "THIRD_PARTY_NOTICES.txt";
        let bytes = regular(&bundle.join(name))?;
        let expected = format!("{}  {name}", digest(&bytes));
        ensure!(
            lines.iter().filter(|l| **l == expected).count() == 1,
            "Bundle notice checksum mismatch"
        );
        files.push((name, bytes));
    }
    directory(prefix)?;
    let prefix = prefix.canonicalize()?;
    let root = prefix.join("lib/nanoleaf-native");
    directory(&root)?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(root.join("install.lock"))?;
    rustix::fs::flock(&lock, rustix::fs::FlockOperation::NonBlockingLockExclusive)?;
    let id = digest(&manifest);
    let version = version_path(&root, &id)?;
    let state_path = root.join("install.json");
    let old: Option<State> = if state_path.exists() {
        Some(serde_json::from_slice(&regular(&state_path)?)?)
    } else {
        None
    };
    let bin = prefix.join("bin");
    directory(&bin)?;
    let entry = data.join("applications/org.spingiantcrm.NanoleafNative.desktop");
    directory(entry.parent().unwrap())?;
    let command = bin.join("nanoleaf-native");
    let existing_entry = if entry.exists() {
        Some(String::from_utf8(regular(&entry)?)?)
    } else {
        None
    };
    if let Some(old) = &old {
        ensure!(
            existing_entry.as_deref() == Some(old.launcher.as_str()),
            "Native launcher changed externally; preserve it before upgrading"
        );
        ensure!(
            fs::read_link(&command)?
                == version_path(&root, &old.current)?.join("bin/nanoleaf-native"),
            "Native command changed externally"
        );
    } else {
        ensure!(
            fs::symlink_metadata(&command).is_err(),
            "An unrelated native command already exists"
        );
        if let Some(content) = &existing_entry {
            ensure!(content.starts_with("[Desktop Entry]\nType=Application\nVersion=1.0\nName=Nanoleaf Screen Mirror (Rust)\n") && content.ends_with("X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n"), "An unrelated launcher already exists");
        }
    }
    directory(&version)?;
    directory(&version.join("bin"))?;
    for (name, bytes) in files {
        let dest = version.join(name);
        if dest.exists() {
            ensure!(
                regular(&dest)? == bytes,
                "Installed version modified: {name}"
            );
        } else {
            let mut f = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(if name.starts_with("bin/") {
                    0o755
                } else {
                    0o644
                })
                .open(dest)?;
            f.write_all(&bytes)?;
            f.sync_all()?;
        }
    }
    atomic(&version.join("SHA256SUMS"), &manifest, 0o644)?;
    let launcher = desktop(&version.join("bin/nanoleaf-native"))?;
    let state = State {
        current: id.clone(),
        previous: old.as_ref().and_then(|s| {
            if s.current == id {
                s.previous.clone()
            } else {
                Some(s.current.clone())
            }
        }),
        launcher: launcher.clone(),
        original_launcher: old
            .as_ref()
            .map_or(existing_entry.clone(), |s| s.original_launcher.clone()),
    };
    let publish = (|| {
        atomic(&entry, launcher.as_bytes(), 0o600)?;
        link(&command, &version.join("bin/nanoleaf-native"))?;
        atomic(&state_path, &serde_json::to_vec_pretty(&state)?, 0o600)
    })();
    if publish.is_err() {
        if let Some(content) = existing_entry {
            let _ = atomic(&entry, content.as_bytes(), 0o600);
        } else {
            let _ = fs::remove_file(&entry);
        }
        if let Some(old) = &old {
            let _ = link(
                &command,
                &version_path(&root, &old.current)?.join("bin/nanoleaf-native"),
            );
        } else {
            let _ = fs::remove_file(&command);
        }
    }
    publish?;
    Ok(version)
}
pub fn rollback(prefix: &Path, data: &Path) -> Result<PathBuf> {
    let prefix = prefix.canonicalize()?;
    let root = prefix.join("lib/nanoleaf-native");
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(root.join("install.lock"))?;
    rustix::fs::flock(&lock, rustix::fs::FlockOperation::NonBlockingLockExclusive)?;
    let state_path = root.join("install.json");
    let mut state: State = serde_json::from_slice(&regular(&state_path)?)?;
    let id = state
        .previous
        .clone()
        .context("No previous native version is available")?;
    let version = version_path(&root, &id)?;
    // Reuse checksum verification, preserving the original install history.
    let manifest = regular(&version.join("SHA256SUMS"))?;
    ensure!(digest(&manifest) == id, "Installed manifest was modified");
    for name in FILES {
        let line = format!("{}  {name}", digest(&regular(&version.join(name))?));
        ensure!(
            std::str::from_utf8(&manifest)?.lines().any(|l| l == line),
            "Rollback checksum mismatch: {name}"
        );
    }
    let lines: Vec<_> = std::str::from_utf8(&manifest)?.lines().collect();
    ensure!(
        lines.len() == FILES.len() || lines.len() == FILES.len() + 1,
        "Invalid rollback manifest"
    );
    if lines.len() == FILES.len() + 1 {
        let name = "THIRD_PARTY_NOTICES.txt";
        let line = format!("{}  {name}", digest(&regular(&version.join(name))?));
        ensure!(
            lines.iter().filter(|l| **l == line).count() == 1,
            "Rollback notice checksum mismatch"
        );
    }
    let entry = data.join("applications/org.spingiantcrm.NanoleafNative.desktop");
    ensure!(
        regular(&entry)? == state.launcher.as_bytes(),
        "Native launcher changed externally"
    );
    let command = prefix.join("bin/nanoleaf-native");
    ensure!(
        fs::read_link(&command)?
            == version_path(&root, &state.current)?.join("bin/nanoleaf-native"),
        "Native command changed externally"
    );
    let launcher = desktop(&version.join("bin/nanoleaf-native"))?;
    let old_launcher = state.launcher.clone();
    let old_current = state.current.clone();
    state.previous = Some(state.current);
    state.current = id;
    state.launcher = launcher.clone();
    let publish = (|| {
        atomic(&entry, launcher.as_bytes(), 0o600)?;
        link(&command, &version.join("bin/nanoleaf-native"))?;
        atomic(&state_path, &serde_json::to_vec_pretty(&state)?, 0o600)
    })();
    if publish.is_err() {
        let _ = atomic(&entry, old_launcher.as_bytes(), 0o600);
        let _ = link(
            &command,
            &version_path(&root, &old_current)?.join("bin/nanoleaf-native"),
        );
    }
    publish?;
    Ok(version)
}
pub fn user_data() -> Result<PathBuf> {
    Ok(std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or(
            PathBuf::from(std::env::var_os("HOME").context("Home directory")?).join(".local/share"),
        ))
}
pub fn refresh_desktop() -> Result<()> {
    ensure!(
        std::process::Command::new("kbuildsycoca6")
            .arg("--noincremental")
            .status()?
            .success(),
        "KDE application cache refresh failed; installed files are retained"
    );
    Ok(())
}
/// An opt-in tray autostart entry; never alters the Python autostart file.
pub fn autostart(enabled: bool) -> Result<()> {
    let data = user_data()?;
    let launcher = regular(&data.join("applications/org.spingiantcrm.NanoleafNative.desktop"))?;
    // Use the managed command for login, so upgrades and rollback take effect.
    let mut launcher = launcher;
    if let Some(exec) = std::str::from_utf8(&launcher)?.lines().find_map(|line| {
        line.strip_prefix("Exec=\"")
            .and_then(|v| v.strip_suffix("\" --daemon"))
    }) {
        let exe = PathBuf::from(exec);
        if let Some(prefix) = exe.ancestors().nth(5) {
            if prefix.join("lib/nanoleaf-native/install.json").is_file() {
                launcher = desktop(&prefix.join("bin/nanoleaf-native"))?.into_bytes();
            }
        }
    }
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or(
            PathBuf::from(std::env::var_os("HOME").context("Home directory")?).join(".config"),
        );
    let dir = config.join("autostart");
    directory(&dir)?;
    let path = dir.join("org.spingiantcrm.NanoleafNative.desktop");
    if path.exists() {
        ensure!(
            regular(&path)?.starts_with(b"# Managed by nanoleaf-native\n"),
            "An unrelated autostart entry already exists"
        );
    }
    if enabled {
        let mut content = b"# Managed by nanoleaf-native\n".to_vec();
        content.extend(launcher);
        atomic(&path, &content, 0o600)?;
    } else if path.exists() {
        fs::remove_file(path)?;
    }
    Ok(())
}

/// Remove only the managed command/launcher. Versions and the original launcher
/// remain recoverable, and user configuration and Python files are untouched.
pub fn uninstall(prefix: &Path, data: &Path) -> Result<()> {
    let prefix = prefix.canonicalize()?;
    let root = prefix.join("lib/nanoleaf-native");
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(root.join("install.lock"))?;
    rustix::fs::flock(&lock, rustix::fs::FlockOperation::NonBlockingLockExclusive)?;
    let path = root.join("install.json");
    let state: State = serde_json::from_slice(&regular(&path)?)?;
    let command = prefix.join("bin/nanoleaf-native");
    let entry = data.join("applications/org.spingiantcrm.NanoleafNative.desktop");
    ensure!(
        regular(&entry)? == state.launcher.as_bytes(),
        "Native launcher changed externally"
    );
    ensure!(
        fs::read_link(&command)?
            == version_path(&root, &state.current)?.join("bin/nanoleaf-native"),
        "Native command changed externally"
    );
    if let Some(original) = &state.original_launcher {
        atomic(&entry, original.as_bytes(), 0o600)?;
    } else {
        fs::remove_file(&entry)?;
    }
    fs::remove_file(command)?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    fs::rename(path, root.join(format!("uninstalled-{stamp}.json")))?;
    Ok(())
}
