//! Non-destructive loading and transactional edits of the existing TOML schema.
use anyhow::{bail, ensure, Context, Result};
use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use toml_edit::{DocumentMut, Item};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default)]
pub struct LedProfile {
    pub red_gain: f64,
    pub green_gain: f64,
    pub blue_gain: f64,
    pub led_gamma: f64,
    pub white_balance_temperature: f64,
    pub chroma_compression: f64,
    pub neutral_luminance_gain: f64,
    pub black_luminance_cutoff: f64,
    pub black_luminance_knee: f64,
    pub dark_sample_stabilize_on: f64,
    pub dark_sample_stabilize_off: f64,
    pub color_matrix: Vec<f64>,
}
impl Default for LedProfile {
    fn default() -> Self {
        Self {
            red_gain: 1.0,
            green_gain: 1.0,
            blue_gain: 1.0,
            led_gamma: 1.0,
            white_balance_temperature: 0.0,
            chroma_compression: 0.0,
            neutral_luminance_gain: 1.0,
            black_luminance_cutoff: 0.0032,
            black_luminance_knee: 0.0024,
            dark_sample_stabilize_on: 0.008,
            dark_sample_stabilize_off: 0.025,
            color_matrix: vec![],
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default)]
pub struct Calibration {
    pub schema_version: u32,
    pub calibration_schema_version: u32,
    pub device_zone_count: usize,
    pub output_channel_order: String,
    pub reverse_zones: bool,
    pub calibration_model: String,
    pub corner_anchor_top_left: i64,
    pub corner_anchor_top_right: i64,
    pub corner_anchor_bottom_right: i64,
    pub corner_anchor_bottom_left: i64,
}
impl Default for Calibration {
    fn default() -> Self {
        Self {
            schema_version: 1,
            calibration_schema_version: 1,
            device_zone_count: 0,
            output_channel_order: "grb".into(),
            reverse_zones: false,
            calibration_model: "corner_anchored".into(),
            corner_anchor_top_left: -1,
            corner_anchor_top_right: -1,
            corner_anchor_bottom_right: -1,
            corner_anchor_bottom_left: -1,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default)]
pub struct Config {
    pub schema_version: u32,
    pub calibration_schema_version: u32,
    pub fps: u32,
    pub capture_backend: String,
    pub brightness: f64,
    pub smoothing: f64,
    pub smoothing_speed: f64,
    pub device_vid: u16,
    pub device_pid: u16,
    pub device_zone_count: usize,
    pub capture_monitor: String,
    pub output_channel_order: String,
    pub color_style: String,
    pub accuracy_mode: bool,
    pub motion_preset: String,
    pub light_spread: String,
    pub sampling_quality: String,
    pub sync_mode: String,
    pub predictive_sync_strength: f64,
    pub layout_inset: f64,
    pub layout_scale: f64,
    pub zone_temporal_accumulation: bool,
    pub zone_box_filter_sampling: bool,
    pub blue_noise_dither: bool,
    pub display_gamut: String,
    pub virtual_zone_oversample: usize,
    pub multi_moment_zone_colors: bool,
    pub scene_adaptive_profiles: bool,
    pub prefer_backend: String,
    pub sampling_mode: String,
    pub layout_preset: String,
    pub edge_locality: String,
    pub source_side_counts: Vec<usize>,
    pub zones: Vec<Rect>,
    pub privacy_zones: Vec<Rect>,
    pub start_on_launch: bool,
    pub auto_turn_on: bool,
    pub reverse_zones: bool,
    pub letterbox_detection: bool,
    pub performance_priority: String,
    pub compositor_hdr_mode: bool,
    pub hdr_transfer: String,
    pub hdr_primaries: String,
    pub hdr_max_nits: f64,
    pub sdr_boost_nits: f64,
    pub calibration: Calibration,
    pub led_calibration_profile_sdr: LedProfile,
    pub led_calibration_profile_hdr: LedProfile,
}
impl Default for Config {
    fn default() -> Self {
        Self {
            schema_version: 2,
            calibration_schema_version: 1,
            fps: 60,
            capture_backend: "auto".into(),
            brightness: 1.0,
            smoothing: 0.5,
            smoothing_speed: 0.75,
            device_vid: 0x37fa,
            device_pid: 0x8202,
            device_zone_count: 0,
            capture_monitor: String::new(),
            output_channel_order: "grb".into(),
            color_style: "ambient".into(),
            accuracy_mode: false,
            motion_preset: "responsive".into(),
            light_spread: "balanced".into(),
            sampling_quality: "balanced".into(),
            sync_mode: "standard".into(),
            predictive_sync_strength: 0.35,
            layout_inset: 0.0,
            layout_scale: 1.0,
            zone_temporal_accumulation: true,
            zone_box_filter_sampling: true,
            blue_noise_dither: true,
            display_gamut: "auto".into(),
            virtual_zone_oversample: 0,
            multi_moment_zone_colors: false,
            scene_adaptive_profiles: false,
            prefer_backend: "auto".into(),
            sampling_mode: "auto".into(),
            layout_preset: "edge_strip".into(),
            edge_locality: "balanced".into(),
            source_side_counts: vec![],
            zones: vec![],
            privacy_zones: vec![],
            start_on_launch: false,
            auto_turn_on: true,
            reverse_zones: false,
            letterbox_detection: true,
            performance_priority: "normal".into(),
            compositor_hdr_mode: false,
            hdr_transfer: "srgb".into(),
            hdr_primaries: "bt709".into(),
            hdr_max_nits: 1000.0,
            sdr_boost_nits: 80.0,
            calibration: Calibration::default(),
            led_calibration_profile_sdr: LedProfile::default(),
            led_calibration_profile_hdr: LedProfile::default(),
        }
    }
}

impl Config {
    /// Reuse the existing response controls; preserve colour, calibration,
    /// mapping, capture selection and all scheduling/FPS settings.
    pub fn enable_fast_response(&mut self) {
        self.zone_temporal_accumulation = false;
        self.smoothing = 1.0;
    }
    pub fn validate(&self) -> Result<()> {
        ensure!(
            matches!(self.sync_mode.as_str(), "standard" | "4d"),
            "Unknown sync mode"
        );
        ensure!(
            self.predictive_sync_strength.is_finite()
                && (0.0..=1.0).contains(&self.predictive_sync_strength),
            "Invalid prediction strength"
        );
        ensure!(
            matches!(
                self.capture_backend.as_str(),
                "auto" | "kwin-dbus" | "xdg-portal" | "kmsgrab"
            ),
            "Unknown capture backend"
        );
        ensure!(
            self.schema_version <= 2,
            "Future configuration schema; use the original application"
        );
        ensure!(
            self.calibration_schema_version <= 1
                && self.calibration.schema_version <= 1
                && self.calibration.calibration_schema_version <= 1,
            "Future calibration schema"
        );
        ensure!(
            nanoleaf_core::protocol::supports_usb(self.device_vid, self.device_pid),
            "Unsupported strip USB IDs"
        );
        ensure!(
            self.device_zone_count <= 512,
            "Manual strip count exceeds 512"
        );
        ensure!(
            (1..=240).contains(&self.fps),
            "Target FPS must be between 1 and 240"
        );
        ensure!(
            self.brightness.is_finite() && (0.0..=1.0).contains(&self.brightness),
            "Invalid brightness"
        );
        ensure!(
            self.smoothing.is_finite() && (0.0..=1.0).contains(&self.smoothing),
            "Invalid smoothing"
        );
        ensure!(
            self.smoothing_speed.is_finite() && (0.0..=4.0).contains(&self.smoothing_speed),
            "Invalid smoothing speed"
        );
        ensure!(
            self.layout_inset.is_finite() && self.layout_scale.is_finite(),
            "Invalid layout transform"
        );
        ensure!(
            self.source_side_counts.is_empty()
                || (self.source_side_counts.len() == 4
                    && self.source_side_counts.iter().all(|&v| v <= 512)),
            "Invalid source side counts"
        );
        ensure!(
            matches!(
                self.color_style.as_str(),
                "reference" | "natural" | "ambient" | "vivid" | "punchy"
            ),
            "Unknown colour style"
        );
        let mut order = self.output_channel_order.chars().collect::<Vec<_>>();
        order.sort_unstable();
        ensure!(order == ['b', 'g', 'r'], "Invalid output channel order");
        for zone in self.zones.iter().chain(&self.privacy_zones) {
            ensure!(
                [zone.x, zone.y, zone.w, zone.h]
                    .iter()
                    .all(|v| v.is_finite()),
                "Non-finite zone"
            );
            ensure!(
                zone.x >= 0.0
                    && zone.y >= 0.0
                    && zone.w >= 0.0
                    && zone.h >= 0.0
                    && zone.x <= 1.0
                    && zone.y <= 1.0
                    && zone.w <= 1.0
                    && zone.h <= 1.0,
                "Invalid normalized zone"
            );
        }
        ensure!(
            self.zones.len() <= 512 && self.privacy_zones.len() <= 512,
            "Too many source/privacy zones"
        );
        for profile in [
            &self.led_calibration_profile_sdr,
            &self.led_calibration_profile_hdr,
        ] {
            let values = [
                profile.red_gain,
                profile.green_gain,
                profile.blue_gain,
                profile.led_gamma,
                profile.white_balance_temperature,
                profile.chroma_compression,
                profile.neutral_luminance_gain,
                profile.black_luminance_cutoff,
                profile.black_luminance_knee,
                profile.dark_sample_stabilize_on,
                profile.dark_sample_stabilize_off,
            ];
            ensure!(
                values.iter().all(|v| v.is_finite()),
                "Non-finite LED profile"
            );
            ensure!(
                profile.color_matrix.is_empty() || profile.color_matrix.len() == 9,
                "LED matrix must have 9 entries"
            );
            ensure!(
                profile.color_matrix.iter().all(|v| v.is_finite()),
                "Non-finite LED matrix"
            );
        }
        Ok(())
    }
    pub fn anchors(&self) -> [i64; 4] {
        [
            self.calibration.corner_anchor_top_left,
            self.calibration.corner_anchor_top_right,
            self.calibration.corner_anchor_bottom_right,
            self.calibration.corner_anchor_bottom_left,
        ]
    }
}

pub struct Store {
    pub path: PathBuf,
    pub config: Config,
    original: Vec<u8>,
    pub document: DocumentMut,
}
impl Store {
    /// First launch creates an unconfigured, stopped application. Existing bytes
    /// are never rewritten and a concurrent creator always wins.
    pub fn initialize(path: &Path) -> Result<()> {
        if fs::symlink_metadata(path).is_ok() {
            return Ok(());
        }
        let parent = path.parent().context("Configuration parent")?;
        fs::create_dir_all(parent)?;
        let content = toml::to_string_pretty(&Config::default())?;
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)
        {
            Ok(mut file) => {
                file.write_all(content.as_bytes())?;
                file.sync_all()?;
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(e.into()),
        }
        Ok(())
    }

    pub fn load(path: &Path) -> Result<Self> {
        let original = fs::read(path).context("Read existing configuration")?;
        Self::parse(path, original)
    }
    pub fn parse(path: &Path, original: Vec<u8>) -> Result<Self> {
        ensure!(original.len() <= 1024 * 1024, "Configuration exceeds 1 MiB");
        let text = std::str::from_utf8(&original)?;
        let document = text.parse::<DocumentMut>()?;
        let mut values = text.parse::<toml::Table>()?;
        for table in [
            Some(&values),
            values.get("calibration").and_then(toml::Value::as_table),
        ]
        .into_iter()
        .flatten()
        {
            if let Some(count) = table.get("device_zone_count") {
                ensure!(
                    count.as_integer().is_some_and(|n| (0..=512).contains(&n)),
                    "Invalid manual strip count"
                );
            }
        }
        // Migrations only affect this working representation, never startup I/O.
        let schema = values
            .get("schema_version")
            .and_then(toml::Value::as_integer)
            .unwrap_or(1);
        ensure!(
            (1..=2).contains(&schema),
            "Unsupported configuration schema {schema}"
        );
        let mut cal = values
            .get("calibration")
            .and_then(toml::Value::as_table)
            .cloned()
            .unwrap_or_default();
        for key in [
            "device_zone_count",
            "output_channel_order",
            "reverse_zones",
            "calibration_model",
            "corner_anchor_top_left",
            "corner_anchor_top_right",
            "corner_anchor_bottom_right",
            "corner_anchor_bottom_left",
        ] {
            let missing = match cal.get(key) {
                None => true,
                Some(toml::Value::Integer(v)) => {
                    *v <= 0 && key == "device_zone_count" || *v < 0 && key.starts_with("corner_")
                }
                _ => false,
            };
            if missing {
                if let Some(value) = values.get(key) {
                    cal.insert(key.into(), value.clone());
                }
            }
        }
        values.insert("calibration".into(), toml::Value::Table(cal.clone()));
        if let Some(count) = cal.get("device_zone_count") {
            values.insert("device_zone_count".into(), count.clone());
        }
        for key in ["output_channel_order", "reverse_zones"] {
            if let Some(value) = cal.get(key) {
                values.insert(key.into(), value.clone());
            }
        }
        for kind in ["sdr", "hdr"] {
            let key = format!("led_calibration_profile_{kind}");
            if !values.contains_key(&key) {
                let mut profile = toml::Table::new();
                for field in [
                    "red_gain",
                    "green_gain",
                    "blue_gain",
                    "led_gamma",
                    "white_balance_temperature",
                    "chroma_compression",
                    "neutral_luminance_gain",
                    "black_luminance_cutoff",
                    "black_luminance_knee",
                ] {
                    if let Some(v) = values.get(field) {
                        profile.insert(field.into(), v.clone());
                    }
                }
                values.insert(key, toml::Value::Table(profile));
            }
        }
        let mut config: Config = toml::Value::Table(values).try_into()?;
        config.schema_version = 2;
        config.capture_backend = config.capture_backend.trim().to_ascii_lowercase();
        if matches!(config.capture_backend.as_str(), "kwin" | "kwin_dbus") {
            config.capture_backend = "kwin-dbus".into();
        }
        config.color_style = config.color_style.trim().to_ascii_lowercase();
        config.sampling_mode = config.sampling_mode.trim().to_ascii_lowercase();
        config.sampling_quality = config.sampling_quality.trim().to_ascii_lowercase();
        config.edge_locality = config.edge_locality.trim().to_ascii_lowercase();
        config.motion_preset = config.motion_preset.trim().to_ascii_lowercase();
        config.light_spread = config.light_spread.trim().to_ascii_lowercase();
        config.performance_priority = config.performance_priority.trim().to_ascii_lowercase();
        config.sync_mode = config.sync_mode.trim().to_ascii_lowercase();
        config.output_channel_order = config.output_channel_order.trim().to_ascii_lowercase();
        config.calibration.output_channel_order = config.output_channel_order.clone();
        config.capture_monitor = config.capture_monitor.trim().to_string();
        config.validate()?;
        Ok(Self {
            path: path.into(),
            config,
            original,
            document,
        })
    }

    pub fn save_document(&mut self, document: DocumentMut) -> Result<()> {
        ensure!(
            !fs::symlink_metadata(&self.path)?.file_type().is_symlink(),
            "Refusing to replace a configuration symlink"
        );
        ensure!(
            fs::read(&self.path)? == self.original,
            "Configuration changed externally; reload before saving"
        );
        // Validate a private candidate before creating any persistent files.
        let candidate = document.to_string();
        Self::parse(&self.path, candidate.as_bytes().to_vec())?;
        if candidate.as_bytes() == self.original {
            return Ok(());
        }
        let mut lock_name = self.path.as_os_str().to_os_string();
        lock_name.push(".lock");
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(PathBuf::from(lock_name))?;
        rustix::fs::flock(&lock, rustix::fs::FlockOperation::NonBlockingLockExclusive)
            .context("Another settings save is in progress; retry after it finishes")?;
        ensure!(
            fs::read(&self.path)? == self.original,
            "Configuration changed while waiting for its lock"
        );
        let parent = self.path.parent().context("Configuration parent")?;
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let backup = parent.join(format!("config.toml.native-backup-{stamp}"));
        let temporary = parent.join(format!(".config.toml.native-{stamp}.tmp"));
        let write_private = |path: &Path, bytes: &[u8]| -> Result<()> {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(path)?;
            file.write_all(bytes)?;
            file.sync_all()?;
            Ok(())
        };
        write_private(&backup, &self.original)?;
        if let Err(error) = write_private(&temporary, candidate.as_bytes()) {
            let _ = fs::remove_file(&temporary);
            return Err(error);
        }
        if fs::read(&self.path)? != self.original {
            let _ = fs::remove_file(&temporary);
            bail!("Configuration changed during save");
        }
        fs::rename(&temporary, &self.path)?;
        File::open(parent)?.sync_all()?;
        *self = Self::load(&self.path)?;
        Ok(())
    }
    pub fn save_fast_response(&mut self) -> Result<()> {
        let mut document = self.document.clone();
        for (key, mut value) in [
            ("smoothing", toml_edit::Value::from(1.0)),
            ("zone_temporal_accumulation", toml_edit::Value::from(false)),
        ] {
            if let Some(previous) = document.get(key).and_then(Item::as_value) {
                *value.decor_mut() = previous.decor().clone();
            }
            document[key] = Item::Value(value);
        }
        self.save_document(document)
    }
    /// Select an existing capture implementation without rewriting calibration,
    /// profiles or unrelated settings. Starting/reloading remains explicit.
    pub fn save_capture_backend(&mut self, backend: &str) -> Result<()> {
        ensure!(
            matches!(backend, "auto" | "kwin-dbus" | "xdg-portal"),
            "Unsupported native capture backend"
        );
        if self.document.get("capture_backend").and_then(Item::as_str) == Some(backend) {
            return self.save_document(self.document.clone());
        }
        let mut document = self.document.clone();
        let mut value = toml_edit::Value::from(backend);
        if let Some(previous) = document.get("capture_backend").and_then(Item::as_value) {
            *value.decor_mut() = previous.decor().clone();
        }
        document["capture_backend"] = Item::Value(value);
        self.save_document(document)
    }
    pub fn update_scalar(&self, key: &str, value: toml_edit::Value) -> Result<DocumentMut> {
        ensure!(
            !key.contains('.') && !key.is_empty(),
            "Only a top-level setting is accepted"
        );
        let mut document = self.document.clone();
        document[key] = Item::Value(value);
        Ok(document)
    }
}
