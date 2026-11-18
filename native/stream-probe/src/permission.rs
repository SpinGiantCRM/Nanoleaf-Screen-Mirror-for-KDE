//! The native probe has its own portal token, separate from Python/configuration.
use anyhow::{ensure, Context, Result};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{DirBuilderExt, OpenOptionsExt},
    path::PathBuf,
};
pub struct Permission {
    path: PathBuf,
}
/// The compositor detected by the capture worker. When set, it, not the
/// inherited `XDG_CURRENT_DESKTOP`, chooses the token file: an autostart unit
/// without that variable must never load, invalidate or overwrite the Plasma
/// token on Hyprland (or the reverse).
static DETECTED: std::sync::OnceLock<crate::compositor::Compositor> = std::sync::OnceLock::new();
pub fn set_compositor(compositor: crate::compositor::Compositor) {
    let _ = DETECTED.set(compositor);
}
impl Permission {
    pub fn user() -> Result<Self> {
        let root = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
            .context("No config directory")?;
        Ok(Self {
            path: root
                .join("nanoleaf-native-stream-probe")
                .join(match DETECTED.get() {
                    Some(compositor) => compositor_token_name(*compositor),
                    None => token_name(std::env::var("XDG_CURRENT_DESKTOP").ok().as_deref()),
                }),
        })
    }
    pub fn load(&self) -> Result<Option<String>> {
        let fd = match rustix::fs::open(
            &self.path,
            rustix::fs::OFlags::RDONLY
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::CLOEXEC
                | rustix::fs::OFlags::NONBLOCK,
            rustix::fs::Mode::empty(),
        ) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(e) => return Err(e.into()),
        };
        let file = File::from(fd);
        ensure!(
            file.metadata()?.is_file(),
            "Invalid native portal token storage"
        );
        let mut value = String::new();
        file.take(4097).read_to_string(&mut value)?;
        ensure!(
            !value.is_empty() && value.len() <= 4096 && value.trim() == value,
            "Invalid native portal token"
        );
        Ok(Some(value))
    }
    pub fn save(&self, value: &str) -> Result<()> {
        ensure!(
            !value.is_empty() && value.len() <= 4096 && value.trim() == value,
            "Invalid returned portal token"
        );
        let dir = self.path.parent().context("Invalid token path")?;
        std::fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(dir)?;
        ensure!(
            !std::fs::symlink_metadata(dir)?.file_type().is_symlink(),
            "Native token directory is a symlink"
        );
        if let Ok(meta) = std::fs::symlink_metadata(&self.path) {
            ensure!(
                meta.is_file() && !meta.file_type().is_symlink(),
                "Native token path is not a regular file"
            );
        }
        let temp = dir.join(format!(".portal-token-{}", std::process::id()));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)?;
        let result = (|| -> Result<()> {
            file.write_all(value.as_bytes())?;
            file.sync_all()?;
            std::fs::rename(&temp, &self.path)?;
            File::open(dir)?.sync_all()?;
            Ok(())
        })();
        if result.is_err() {
            let _ = std::fs::remove_file(temp);
        }
        result
    }
    pub fn invalidate(&self) -> Result<()> {
        match std::fs::symlink_metadata(&self.path) {
            Ok(m) => {
                ensure!(
                    m.is_file() && !m.file_type().is_symlink(),
                    "Invalid native token path"
                );
                std::fs::remove_file(&self.path)?;
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        };
        Ok(())
    }
}
/// Restore tokens are issued by each desktop's portal backend. Keep them
/// apart so alternating Plasma and Hyprland logins do not discard each other's
/// remembered permission. Plasma keeps the original file name.
fn compositor_token_name(compositor: crate::compositor::Compositor) -> &'static str {
    match compositor {
        crate::compositor::Compositor::KWin => "portal-token",
        crate::compositor::Compositor::Hyprland => "portal-token-hyprland",
    }
}
/// Diagnostic probes that do not detect the compositor use the desktop name.
fn token_name(desktop: Option<&str>) -> &'static str {
    if desktop.is_some_and(|d| d.split(':').any(|n| n.eq_ignore_ascii_case("Hyprland"))) {
        "portal-token-hyprland"
    } else {
        "portal-token"
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn plasma_keeps_its_token_and_hyprland_has_its_own() {
        assert_eq!(token_name(Some("KDE")), "portal-token");
        assert_eq!(token_name(None), "portal-token");
        assert_eq!(token_name(Some("Hyprland")), "portal-token-hyprland");
        assert_eq!(
            token_name(Some("Hyprland:wlroots")),
            "portal-token-hyprland"
        );
        assert_eq!(token_name(Some("KDE:NotHyprlandish")), "portal-token");
        use crate::compositor::Compositor;
        assert_eq!(compositor_token_name(Compositor::KWin), "portal-token");
        assert_eq!(
            compositor_token_name(Compositor::Hyprland),
            "portal-token-hyprland"
        );
    }
    use std::os::unix::fs::{symlink, PermissionsExt};
    #[test]
    fn private_bounded_separate_token_store() {
        let dir = std::env::temp_dir().join(format!("nanoleaf-permission-{}", std::process::id()));
        let token = Permission {
            path: dir.join("native/portal-token"),
        };
        assert!(token.load().unwrap().is_none());
        token.save("test-permission-one").unwrap();
        assert_eq!(
            token.load().unwrap().as_deref(),
            Some("test-permission-one")
        );
        assert_eq!(
            std::fs::metadata(&token.path).unwrap().permissions().mode() & 0o777,
            0o600
        );
        token.save("test-permission-two").unwrap();
        assert_eq!(
            token.load().unwrap().as_deref(),
            Some("test-permission-two")
        );
        assert!(token.save(&"a".repeat(4097)).is_err());
        token.invalidate().unwrap();
        assert!(token.load().unwrap().is_none());
        symlink("missing", &token.path).unwrap();
        assert!(token.load().is_err());
        assert!(token.save("test").is_err());
        assert!(token.invalidate().is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }
}
