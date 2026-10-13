//! Legacy-compatible, versioned measured-profile files; never auto-apply on import.
use crate::config::{Config, LedProfile};
use anyhow::{ensure, Context, Result};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::OpenOptionsExt,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
const KIND: &str = "nanoleaf-kde-sync-led-calibration-profile";
const LIMIT: u64 = 1024 * 1024;
fn validate(preset: &str, profile: &LedProfile) -> Result<()> {
    ensure!(
        matches!(preset, "sdr" | "hdr"),
        "Unknown profile display preset"
    );
    let config = Config {
        led_calibration_profile_sdr: profile.clone(),
        ..Default::default()
    };
    config.validate()
}
pub fn encode(preset: &str, profile: &LedProfile) -> Result<String> {
    validate(preset, profile)?;
    let mut values = serde_json::to_value(profile)?;
    values["profile_kind"] = KIND.into();
    values["schema_version"] = 1.into();
    Ok(serde_json::to_string_pretty(
        &serde_json::json!({"display_preset":preset,"profile":values}),
    )? + "\n")
}
pub fn decode(raw: &str) -> Result<(String, LedProfile)> {
    ensure!(raw.len() as u64 <= LIMIT, "Profile exceeds 1 MiB");
    let values: serde_json::Value = serde_json::from_str(raw)?;
    let profile = values
        .get("profile")
        .context("Missing LED profile object")?;
    ensure!(
        profile.get("profile_kind").and_then(|v| v.as_str()) == Some(KIND),
        "Unrecognized LED calibration profile"
    );
    ensure!(
        profile.get("schema_version").and_then(|v| v.as_u64()) == Some(1),
        "Unsupported LED profile schema"
    );
    let preset = values
        .get("display_preset")
        .and_then(|v| v.as_str())
        .unwrap_or("sdr")
        .trim()
        .to_ascii_lowercase();
    let parsed: LedProfile = serde_json::from_value(profile.clone())?;
    validate(&preset, &parsed)?;
    Ok((preset, parsed))
}
fn read_bounded(path: &Path) -> Result<Vec<u8>> {
    let fd = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY | rustix::fs::OFlags::NONBLOCK | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )?;
    let file = File::from(fd);
    ensure!(file.metadata()?.is_file(), "Choose a regular profile file");
    ensure!(file.metadata()?.len() <= LIMIT, "Profile exceeds 1 MiB");
    let mut data = Vec::new();
    file.take(LIMIT + 1).read_to_end(&mut data)?;
    ensure!(data.len() as u64 <= LIMIT, "Profile grew beyond 1 MiB");
    Ok(data)
}
pub fn load(path: &Path) -> Result<(String, LedProfile)> {
    decode(std::str::from_utf8(&read_bounded(path)?)?)
}
pub fn export(path: &Path, preset: &str, profile: &LedProfile) -> Result<Option<PathBuf>> {
    ensure!(
        path.extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("json")),
        "Choose a .json profile filename"
    );
    let raw = encode(preset, profile)?;
    let existing = match fs::symlink_metadata(path) {
        Ok(meta) => {
            ensure!(
                !meta.file_type().is_symlink(),
                "Refusing to replace a profile symlink"
            );
            Some(read_bounded(path)?)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
        Err(e) => return Err(e.into()),
    };
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let name = path
        .file_name()
        .context("Profile filename required")?
        .to_string_lossy();
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let temp = parent.join(format!(".{name}.native-{stamp}.tmp"));
    let result = (|| -> Result<Option<PathBuf>> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)?;
        file.write_all(raw.as_bytes())?;
        file.sync_all()?;
        let backup = if let Some(original) = &existing {
            ensure!(
                read_bounded(path)? == *original,
                "Profile changed externally; choose again"
            );
            let backup = parent.join(format!("{name}.native-backup-{stamp}"));
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&backup)?;
            file.write_all(original)?;
            file.sync_all()?;
            Some(backup)
        } else {
            ensure!(
                !path.exists(),
                "Profile destination appeared externally; choose again"
            );
            None
        };
        fs::rename(&temp, path)?;
        File::open(parent)?.sync_all()?;
        Ok(backup)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}
