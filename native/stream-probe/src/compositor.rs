//! Per-compositor stream colour contracts. Each branch is enabled only for the
//! compositor family whose portal output was validated; see
//! docs/KWIN_6_8_COMPATIBILITY.md and docs/HYPRLAND_COMPATIBILITY.md.
use anyhow::{ensure, Context, Result};
use std::{
    io::{Read, Write},
    os::unix::net::UnixStream,
    path::PathBuf,
    time::Duration,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Compositor {
    /// KWin 6.7/6.8: ARGB8888, untagged, sRGB-labelled SDR render target.
    KWin,
    /// Hyprland 0.57 with xdg-desktop-portal-hyprland: ARGB8888, untagged,
    /// SDR sRGB-encoded composition even when the output runs HDR (PQ).
    /// Implicit synchronisation only; xdph offers no SyncTimeline buffers.
    Hyprland,
}

impl Compositor {
    pub fn supports_explicit_sync(self) -> bool {
        matches!(self, Self::KWin)
    }
}

pub fn verified_kwin_family(version: &str) -> bool {
    // Exact 6.7.5/6.8.0 upstream paths use an ARGB8888 source and the same
    // sRGB-labelled SDR render target. Per-frame format/colour guards remain.
    // See docs/KWIN_6_8_COMPATIBILITY.md for source and live validation limits.
    let core = version.trim().split('-').next().unwrap_or_default();
    let parts: Vec<_> = core.split('.').collect();
    matches!(parts.as_slice(),["6","7"|"8",patch] if patch.parse::<u16>().is_ok_and(|value| value < 50))
}

pub fn verified_hyprland_family(version: &str) -> bool {
    // Live-validated on 0.57.2 with xdph 1.5.0 under `cm = "hdr"`: SDR sRGB
    // bytes are returned unchanged. A later family must be re-probed first.
    let core = version.trim().trim_start_matches('v');
    let core = core.split(['-', '+']).next().unwrap_or_default();
    let parts: Vec<_> = core.split('.').collect();
    matches!(parts.as_slice(), ["0", "57", patch] if patch.parse::<u16>().is_ok())
}

fn kwin_version(connection: &zbus::blocking::Connection) -> Result<String> {
    let kwin = zbus::blocking::Proxy::new(connection, "org.kde.KWin", "/KWin", "org.kde.KWin")?;
    let info: String = kwin.call("supportInformation", &())?;
    info.lines()
        .find_map(|l| l.strip_prefix("KWin version: "))
        .map(str::to_owned)
        .context("Cannot establish KWin colour contract")
}

fn hyprland_socket() -> Option<PathBuf> {
    let signature = std::env::var_os("HYPRLAND_INSTANCE_SIGNATURE")?;
    let runtime = std::env::var_os("XDG_RUNTIME_DIR")?;
    let signature = PathBuf::from(signature);
    // A signature is one path component; never follow a crafted path.
    let mut components = signature.components();
    if !matches!(
        (components.next(), components.next()),
        (Some(std::path::Component::Normal(_)), None)
    ) {
        return None;
    }
    Some(
        PathBuf::from(runtime)
            .join("hypr")
            .join(signature)
            .join(".socket.sock"),
    )
}

/// Ask the running Hyprland instance itself; a stale environment variable
/// without a live socket never selects the Hyprland contract.
fn hyprland_version() -> Option<String> {
    let mut stream = UnixStream::connect(hyprland_socket()?).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .ok()?;
    stream.write_all(b"j/version").ok()?;
    let mut reply = String::new();
    stream.take(65_536).read_to_string(&mut reply).ok()?;
    parse_hyprland_version(&reply)
}

fn parse_hyprland_version(reply: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(reply).ok()?;
    value["version"]
        .as_str()
        .or_else(|| value["tag"].as_str())
        .map(str::to_owned)
}

/// KWin is checked first and keeps its original errors; Hyprland is only
/// considered when KWin does not own its bus name.
pub fn detect(connection: &zbus::blocking::Connection) -> Result<Compositor> {
    let bus = zbus::blocking::fdo::DBusProxy::new(connection)?;
    let kwin_running = bus
        .name_has_owner(zbus::names::BusName::try_from("org.kde.KWin")?)
        .unwrap_or(false);
    if kwin_running {
        let version = kwin_version(connection)?;
        ensure!(
            verified_kwin_family(&version),
            "Stream colour contract is verified for KWin 6.7/6.8; running {version}. Select KWin ScreenShot2 until this compositor contract is verified"
        );
        return Ok(Compositor::KWin);
    }
    if let Some(version) = hyprland_version() {
        ensure!(
            verified_hyprland_family(&version),
            "Stream colour contract is verified for Hyprland 0.57; running {version}. Re-run the stream probe on this release before enabling it"
        );
        return Ok(Compositor::Hyprland);
    }
    anyhow::bail!(
        "Stream colour contract is verified only for KWin 6.7/6.8 and Hyprland 0.57; no supported compositor is running"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn compositor_contract_allows_only_researched_release_families() {
        for version in ["6.7.5", "6.7.5-3.1", "6.8.0", "6.8.1", " 6.8.0 "] {
            assert!(verified_kwin_family(version), "{version}");
        }
        for version in [
            "",
            "6.6.5",
            "6.9.0",
            "7.0.0",
            "6.8",
            "6.8.",
            "6.8.90.1",
            "6.8.80",
            "6.8.90",
            "6.7.80",
            "6.8.not-a-release",
            "6.80.0",
        ] {
            assert!(!verified_kwin_family(version), "{version}");
        }
    }
    #[test]
    fn hyprland_contract_allows_only_the_probed_family() {
        for version in ["0.57.2", "v0.57.2", "0.57.0", " 0.57.3 ", "0.57.2-1"] {
            assert!(verified_hyprland_family(version), "{version}");
        }
        for version in [
            "", "0.56.9", "0.58.0", "1.0.0", "0.57", "0.57.", "0.57.x", "0.570.1", "57.2",
        ] {
            assert!(!verified_hyprland_family(version), "{version}");
        }
    }
    #[test]
    fn hyprland_version_reply_is_parsed_from_ipc_json() {
        assert_eq!(
            parse_hyprland_version(r#"{"branch":"v0.57.2","version":"0.57.2","tag":"v0.57.2"}"#)
                .as_deref(),
            Some("0.57.2")
        );
        assert_eq!(
            parse_hyprland_version(r#"{"tag":"v0.57.1"}"#).as_deref(),
            Some("v0.57.1")
        );
        assert_eq!(parse_hyprland_version("unknown request"), None);
        assert_eq!(parse_hyprland_version(r#"{"version":57}"#), None);
    }
    #[test]
    fn only_kwin_offers_explicit_sync() {
        assert!(Compositor::KWin.supports_explicit_sync());
        assert!(!Compositor::Hyprland.supports_explicit_sync());
    }
}
