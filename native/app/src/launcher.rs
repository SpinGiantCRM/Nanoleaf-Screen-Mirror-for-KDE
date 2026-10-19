//! Separate native application identity for KWin's executable-based permission check.
use anyhow::{ensure, Context, Result};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    os::unix::fs::OpenOptionsExt,
    path::PathBuf,
};
pub fn install() -> Result<PathBuf> {
    let exe = std::env::current_exe()?.canonicalize()?;
    let exec = exe.to_str().context("Non-UTF8 executable path")?;
    ensure!(
        !exec
            .chars()
            .any(|c| c.is_control() || matches!(c, '"' | '\\' | '`' | '$' | '%')),
        "Unsupported desktop executable path"
    );
    let data = PathBuf::from(std::env::var_os("XDG_DATA_HOME").unwrap_or_else(|| {
        PathBuf::from(std::env::var_os("HOME").unwrap_or_default())
            .join(".local/share")
            .into_os_string()
    }))
    .join("applications");
    fs::create_dir_all(&data)?;
    let path = data.join("org.spingiantcrm.NanoleafNative.desktop");
    let icon = crate::package::desktop_icon(&exe)?;
    let content=format!("[Desktop Entry]\nType=Application\nVersion=1.0\nName=Nanoleaf Screen Mirror (Rust)\nComment=Native single-strip screen mirror\nExec=\"{exec}\" --daemon\nTryExec={exec}\nIcon={icon}\nTerminal=false\nCategories=Utility;\nStartupNotify=false\nX-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n");
    if path.exists() {
        ensure!(fs::read_to_string(&path)?==content,"Native launcher already exists with different contents; preserve it and update manually");
    } else {
        let mut f = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)?;
        f.write_all(content.as_bytes())?;
        f.sync_all()?;
    }
    ensure!(
        std::process::Command::new("kbuildsycoca6")
            .arg("--noincremental")
            .status()?
            .success(),
        "KDE application cache refresh failed"
    );
    Ok(path)
}
