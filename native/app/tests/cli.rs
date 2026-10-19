use std::{fs, path::PathBuf, process::Command};

struct Home(PathBuf);
impl Home {
    fn new(name: &str) -> Self {
        let path = std::env::temp_dir().join(format!("nanoleaf-cli-{name}-{}", std::process::id()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn run(&self, argument: &str) -> std::process::Output {
        Command::new(env!("CARGO_BIN_EXE_nanoleaf-native"))
            .env_clear()
            .env("HOME", &self.0)
            .env("XDG_CONFIG_HOME", self.0.join("config"))
            .env("XDG_DATA_HOME", self.0.join("data"))
            .env("XDG_STATE_HOME", self.0.join("state"))
            .env("XDG_RUNTIME_DIR", self.0.join("runtime"))
            .arg(argument)
            .output()
            .unwrap()
    }
}
impl Drop for Home {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn help_succeeds_without_desktop_or_configuration_and_creates_no_user_files() {
    let home = Home::new("help");
    for flag in ["--help", "-h"] {
        let output = home.run(flag);
        assert!(
            output.status.success(),
            "{flag}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let help = String::from_utf8(output.stdout).unwrap();
        for command in ["--settings", "--stop", "--doctor", "--install-native"] {
            assert!(help.contains(command), "missing help for {command}");
        }
        assert!(output.stderr.is_empty());
        assert_eq!(fs::read_dir(&home.0).unwrap().count(), 0);
    }
}

#[test]
fn version_and_unknown_option_do_not_initialize_configuration() {
    let home = Home::new("options");
    let version = home.run("--version");
    assert!(version.status.success());
    assert_eq!(
        String::from_utf8(version.stdout).unwrap().trim(),
        format!("nanoleaf-native {}", env!("CARGO_PKG_VERSION"))
    );
    let unknown = home.run("--unknown-option");
    assert!(!unknown.status.success());
    assert!(String::from_utf8(unknown.stderr)
        .unwrap()
        .contains("--help"));
    assert_eq!(fs::read_dir(&home.0).unwrap().count(), 0);
}
