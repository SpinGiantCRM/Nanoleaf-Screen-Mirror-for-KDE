//! Bounded, allowlisted diagnostics. No status messages, paths, pixels or configuration.
use crate::service::Status;
use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::VecDeque,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt},
    path::{Component, Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc, Arc, Mutex,
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};
const MAX_REPORT_BYTES: u64 = 200 * 1024;
const SAMPLE_LIMIT: usize = 120;
const EVENT_LIMIT: usize = 32;
static UNIQUE: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum FailureKind {
    CaptureStalled,
    CaptureEnded,
    CaptureFailed,
    UsbDisconnected,
    UsbInitialization,
    SessionInterrupted,
}
impl FailureKind {
    pub fn title(&self) -> &'static str {
        match self {
            Self::CaptureStalled => "Capture stopped delivering frames",
            Self::CaptureEnded => "Screen sharing ended",
            Self::CaptureFailed => "Screen capture failed",
            Self::UsbDisconnected => "Strip connection interrupted",
            Self::UsbInitialization => "Strip connection failed",
            Self::SessionInterrupted => "Desktop session interrupted",
        }
    }
    pub fn body(&self) -> &'static str {
        match self {
            Self::CaptureStalled => "No new capture frames arrived. Choose Restart mirroring to request capture again.",
            Self::CaptureEnded => "The capture worker or screen-sharing session ended. Choose Restart mirroring to request capture again.",
            Self::CaptureFailed => "Capture could not continue. Choose Restart mirroring to request capture again.",
            Self::UsbDisconnected => "USB communication was interrupted. Check the strip connection; mirroring will retry when available.",
            Self::UsbInitialization => "The strip could not be opened or initialized. Check its USB connection and permissions.",
            Self::SessionInterrupted => "The desktop session was interrupted. Choose Restart mirroring after the session is ready.",
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Failure {
    pub kind: FailureKind,
    pub at_unix_ms: u64,
    pub retrying: bool,
}
impl Failure {
    pub fn new(kind: FailureKind, retrying: bool) -> Self {
        Self {
            kind,
            at_unix_ms: now_ms(),
            retrying,
        }
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct BuildIdentity {
    /// True only while the background collector has not finished its first read.
    #[serde(default)]
    pub identity_pending: bool,
    pub app_sha256: Option<String>,
    pub capture_helper_sha256: Option<String>,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Environment {
    pub wayland_session: bool,
    pub kde_session: bool,
    pub kernel_release: Option<String>,
    pub nvidia_driver_version: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Backend {
    KwinScreenshot,
    PortalVulkan,
    Preview,
    Unknown,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Sample {
    pub at_unix_ms: u64,
    pub running: bool,
    pub preview: bool,
    pub backend: Backend,
    pub frames: u64,
    pub dropped_frames: u64,
    pub missed_deadlines: u64,
    pub reconnects: u64,
    pub capture_ms: Option<f64>,
    pub processing_ms: Option<f64>,
    pub usb_ms: Option<f64>,
    pub response_ms: Option<f64>,
    pub effective_fps: Option<f64>,
    pub failure: Option<Failure>,
}
fn number(value: f64) -> Option<f64> {
    value.is_finite().then_some(value).filter(|v| *v >= 0.0)
}
impl Sample {
    fn from_status(status: &Status, at_unix_ms: u64) -> Self {
        let backend = if status.backend.starts_with("kwin-dbus") {
            Backend::KwinScreenshot
        } else if status.backend.starts_with("xdg-portal") {
            Backend::PortalVulkan
        } else if status.preview {
            Backend::Preview
        } else {
            Backend::Unknown
        };
        Self {
            at_unix_ms,
            running: status.running,
            preview: status.preview,
            backend,
            frames: status.frames,
            dropped_frames: status.dropped_frames,
            missed_deadlines: status.missed_deadlines,
            reconnects: status.reconnects,
            capture_ms: number(status.capture_ms),
            processing_ms: number(status.processing_ms),
            usb_ms: number(status.usb_ms),
            response_ms: number(status.response_ms),
            effective_fps: number(status.effective_fps),
            failure: status.failure.clone(),
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    LifecycleChanged,
    FailureChanged,
    FailureCleared,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub at_unix_ms: u64,
    pub kind: EventKind,
    pub running: bool,
    pub preview: bool,
    pub failure: Option<Failure>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ReportSource {
    CurrentService,
    CachedSession,
}
/// A frozen failure episode, with its own binary/environment provenance.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FailureRecord {
    pub captured_at_unix_ms: u64,
    pub app_version: String,
    pub build: BuildIdentity,
    pub environment: Environment,
    pub current: Sample,
    pub events: Vec<Event>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Report {
    pub schema_version: u32,
    pub generated_at_unix_ms: u64,
    pub source: ReportSource,
    /// Cached reports never establish that the service or capture is currently running.
    pub stale: bool,
    pub app_version: String,
    pub build: BuildIdentity,
    pub environment: Environment,
    pub current: Sample,
    pub samples: Vec<Sample>,
    pub events: Vec<Event>,
    #[serde(default)]
    pub last_failure: Option<FailureRecord>,
}
struct State {
    build: BuildIdentity,
    environment: Environment,
    current: Sample,
    samples: VecDeque<Sample>,
    events: VecDeque<Event>,
    sampled_at: Option<u64>,
    persisted_at: u64,
    observed: bool,
    last_failure: Option<FailureRecord>,
    failure_revision: u64,
    failure_this_session: bool,
}
impl State {
    fn new() -> Self {
        Self {
            build: BuildIdentity {
                identity_pending: true,
                ..BuildIdentity::default()
            },
            environment: Environment::default(),
            current: Sample::from_status(&Status::default(), now_ms()),
            samples: VecDeque::new(),
            events: VecDeque::new(),
            sampled_at: None,
            persisted_at: 0,
            observed: false,
            last_failure: None,
            failure_revision: 0,
            failure_this_session: false,
        }
    }
    fn observe_at(&mut self, status: &Status, elapsed_ms: u64, at_unix_ms: u64) -> bool {
        let lifecycle = !self.observed
            || self.current.running != status.running
            || self.current.preview != status.preview;
        let failure = self.current.failure != status.failure;
        if lifecycle || failure {
            let kind = if failure {
                if status.failure.is_some() {
                    EventKind::FailureChanged
                } else {
                    EventKind::FailureCleared
                }
            } else {
                EventKind::LifecycleChanged
            };
            self.events.push_back(Event {
                at_unix_ms,
                kind,
                running: status.running,
                preview: status.preview,
                failure: status.failure.clone(),
            });
            if self.events.len() > EVENT_LIMIT {
                self.events.pop_front();
            }
        }
        self.current = Sample::from_status(status, at_unix_ms);
        self.observed = true;
        if failure
            && status
                .failure
                .as_ref()
                .is_some_and(|f| f.kind != FailureKind::SessionInterrupted)
        {
            self.last_failure = Some(FailureRecord {
                captured_at_unix_ms: at_unix_ms,
                app_version: env!("CARGO_PKG_VERSION").into(),
                build: self.build.clone(),
                environment: self.environment.clone(),
                current: self.current.clone(),
                events: self.events.iter().cloned().collect(),
            });
            self.failure_this_session = true;
            self.failure_revision = self.failure_revision.saturating_add(1);
        }
        if self
            .sampled_at
            .is_none_or(|last| elapsed_ms.saturating_sub(last) >= 1000)
        {
            self.samples.push_back(self.current.clone());
            if self.samples.len() > SAMPLE_LIMIT {
                self.samples.pop_front();
            }
            self.sampled_at = Some(elapsed_ms);
        }
        let persist = lifecycle || failure || elapsed_ms.saturating_sub(self.persisted_at) >= 5000;
        if persist {
            self.persisted_at = elapsed_ms;
        }
        persist
    }
    fn load_retained(&mut self, retained: Option<FailureRecord>) {
        if !self.failure_this_session {
            self.last_failure = retained;
        }
    }
    fn complete_identity(&mut self, build: BuildIdentity, environment: Environment) {
        self.build = build;
        self.environment = environment;
        if self.failure_this_session {
            if let Some(failure) = self
                .last_failure
                .as_mut()
                .filter(|f| f.build.identity_pending)
            {
                failure.build = self.build.clone();
                failure.environment = self.environment.clone();
                self.failure_revision = self.failure_revision.saturating_add(1);
            }
        }
    }
    fn report(&self, status: &Status) -> Report {
        self.snapshot(Sample::from_status(status, now_ms()))
    }
    fn snapshot(&self, current: Sample) -> Report {
        Report {
            schema_version: 1,
            generated_at_unix_ms: now_ms(),
            source: ReportSource::CurrentService,
            stale: false,
            app_version: env!("CARGO_PKG_VERSION").into(),
            build: self.build.clone(),
            environment: self.environment.clone(),
            current,
            samples: self.samples.iter().cloned().collect(),
            events: self.events.iter().cloned().collect(),
            last_failure: self.last_failure.clone(),
        }
    }
}
/// A cloneable recorder. Hot-path observation never performs file I/O or serialization.
#[derive(Clone)]
pub struct Recorder {
    state: Arc<Mutex<State>>,
    wake: Option<mpsc::SyncSender<()>>,
    epoch: Instant,
}
impl Default for Recorder {
    fn default() -> Self {
        Self::start()
    }
}
impl Recorder {
    /// Start cheaply; binary hashing and environment reads run only on the actor.
    pub fn start() -> Self {
        Self::with_identity(state_root().ok(), collect_identity)
    }
    fn with_identity(
        root: Option<PathBuf>,
        collect: impl FnOnce() -> (BuildIdentity, Environment) + Send + 'static,
    ) -> Self {
        let state = Arc::new(Mutex::new(State::new()));
        let (wake, receiver) = mpsc::sync_channel(1);
        let actor_state = state.clone();
        let spawned = std::thread::Builder::new()
            .name("native-diagnostics".into())
            .spawn(move || {
                let retained = root.as_ref().and_then(|root| retained_at(root).ok());
                if let Ok(mut state) = actor_state.lock() {
                    state.load_retained(retained);
                }
                let (build, environment) = collect();
                if let Ok(mut state) = actor_state.lock() {
                    state.complete_identity(build, environment);
                }
                let mut saved_revision = 0;
                // Persist identity completion and a new failure, but never rewrite an older episode.
                if let Some(root) = root.as_ref() {
                    persist_state(&actor_state, root, &mut persist_at, &mut saved_revision);
                }
                actor(receiver, actor_state, root, saved_revision, persist_at);
            });
        Self {
            state,
            wake: spawned.ok().map(|_| wake),
            epoch: Instant::now(),
        }
    }
    pub fn observe(&self, status: &Status) {
        let persist = self
            .state
            .lock()
            .map(|mut state| {
                state.observe_at(
                    status,
                    self.epoch.elapsed().as_millis().min(u128::from(u64::MAX)) as u64,
                    now_ms(),
                )
            })
            .unwrap_or(false);
        if persist {
            if let Some(wake) = &self.wake {
                let _ = wake.try_send(());
            }
        }
    }
    pub fn report(&self, status: &Status) -> Report {
        match self.state.lock() {
            Ok(state) => state.report(status),
            Err(_) => State::new().report(status),
        }
    }
}
fn actor(
    receiver: mpsc::Receiver<()>,
    state: Arc<Mutex<State>>,
    root: Option<PathBuf>,
    mut saved_revision: u64,
    mut persist: impl FnMut(&Path, &Report) -> Result<()>,
) {
    loop {
        let final_write = receiver.recv().is_err();
        // A single pending wake coalesces bursts without allocating a queue.
        if let Some(root) = root.as_ref() {
            persist_state(&state, root, &mut persist, &mut saved_revision);
        }
        if final_write {
            break;
        }
    }
}
fn persist_state(
    state: &Mutex<State>,
    root: &Path,
    persist: &mut impl FnMut(&Path, &Report) -> Result<()>,
    saved_revision: &mut u64,
) {
    let Ok(state) = state.lock() else {
        return;
    };
    let report = state.snapshot(state.current.clone());
    let revision = state.failure_revision;
    drop(state);
    if revision != *saved_revision {
        if let Some(failure) = &report.last_failure {
            if persist_failure_at(root, failure).is_ok() {
                *saved_revision = revision;
            }
        }
    }
    let _ = persist(root, &report);
}
fn collect_identity() -> (BuildIdentity, Environment) {
    let build = build_identity();
    let environment = Environment {
        wayland_session: std::env::var_os("WAYLAND_DISPLAY").is_some(),
        kde_session: std::env::var("XDG_CURRENT_DESKTOP")
            .is_ok_and(|s| s.split(':').any(|s| s == "KDE")),
        kernel_release: version_file(Path::new("/proc/sys/kernel/osrelease")),
        nvidia_driver_version: version_file(Path::new("/sys/module/nvidia/version")),
    };
    (build, environment)
}
fn safe_version(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 96
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b".-_+".contains(&c))
}
fn version_file(path: &Path) -> Option<String> {
    let mut value = String::new();
    File::open(path)
        .ok()?
        .take(98)
        .read_to_string(&mut value)
        .ok()?;
    let value = value.trim();
    safe_version(value).then(|| value.to_owned())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}
fn hash_file(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        hash.update(&buffer[..n]);
    }
    Ok(hash.finalize().iter().map(|b| format!("{b:02x}")).collect())
}
fn build_identity() -> BuildIdentity {
    let Ok(executable) = std::env::current_exe().and_then(|p| p.canonicalize()) else {
        return BuildIdentity::default();
    };
    let mut helper = executable
        .parent()
        .map(|p| p.join("nanoleaf-native-capture"));
    if !helper.as_ref().is_some_and(|p| p.is_file()) {
        helper = executable
            .ancestors()
            .find(|p| {
                p.join("app/Cargo.toml").is_file() && p.join("stream-probe/Cargo.toml").is_file()
            })
            .map(|p| p.join("stream-probe/target/release/nanoleaf-stream-probe"));
    }
    BuildIdentity {
        identity_pending: false,
        app_sha256: hash_file(&executable).ok(),
        capture_helper_sha256: helper.and_then(|p| hash_file(&p).ok()),
    }
}
fn state_root() -> Result<PathBuf> {
    let base = match std::env::var_os("XDG_STATE_HOME").filter(|p| !p.is_empty()) {
        Some(base) => PathBuf::from(base),
        None => PathBuf::from(std::env::var_os("HOME").context("Home directory unavailable")?)
            .join(".local/state"),
    };
    ensure!(base.is_absolute(), "State directory must be absolute");
    let app = base.join("nanoleaf-native");
    Ok(app.join("diagnostics"))
}
fn check_components(path: &Path) -> Result<()> {
    ensure!(path.is_absolute(), "Diagnostic directory must be absolute");
    let mut checked = PathBuf::new();
    for component in path.components() {
        ensure!(
            !matches!(component, Component::ParentDir),
            "Invalid diagnostic directory"
        );
        checked.push(component);
        match fs::symlink_metadata(&checked) {
            Ok(meta) => ensure!(
                meta.is_dir() && !meta.file_type().is_symlink(),
                "Unsafe diagnostic directory"
            ),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}
fn private_dir(path: &Path) -> Result<()> {
    if path.file_name().is_some_and(|n| n == "diagnostics") {
        private_dir(path.parent().context("Diagnostic parent directory")?)?;
    }
    check_components(path)?;
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)?;
    check_private_dir(path)
}
fn check_private_dir(path: &Path) -> Result<()> {
    if path.file_name().is_some_and(|n| n == "diagnostics") {
        check_private_dir(path.parent().context("Diagnostic parent directory")?)?;
    }
    check_components(path)?;
    let meta = fs::symlink_metadata(path)?;
    ensure!(
        meta.is_dir() && !meta.file_type().is_symlink(),
        "Unsafe diagnostic directory"
    );
    ensure!(
        meta.uid() == rustix::process::geteuid().as_raw() && meta.mode() & 0o077 == 0,
        "Diagnostic directory must be private"
    );
    Ok(())
}
fn private_file(path: &Path) -> Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags((rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32)
        .open(path)?;
    let meta = file.metadata()?;
    ensure!(
        meta.is_file()
            && meta.uid() == rustix::process::geteuid().as_raw()
            && meta.mode() & 0o077 == 0
            && meta.nlink() == 1,
        "Unsafe diagnostic report"
    );
    ensure!(
        meta.len() <= MAX_REPORT_BYTES,
        "Diagnostic report is too large"
    );
    Ok(file)
}
fn encoded(report: &Report) -> Result<Vec<u8>> {
    ensure!(
        report.samples.len() <= SAMPLE_LIMIT && report.events.len() <= EVENT_LIMIT,
        "Diagnostic report history is too large"
    );
    if let Some(failure) = &report.last_failure {
        validate_failure(failure)?;
    }
    let bytes = serde_json::to_vec_pretty(report)?;
    ensure!(
        bytes.len() as u64 <= MAX_REPORT_BYTES,
        "Diagnostic report is too large"
    );
    Ok(bytes)
}
fn new_file(root: &Path, prefix: &str) -> Result<(PathBuf, File)> {
    for _ in 0..16 {
        let path = root.join(format!(
            "{prefix}-{}-{}-{}.json",
            now_ms(),
            std::process::id(),
            UNIQUE.fetch_add(1, Ordering::Relaxed)
        ));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
            .open(&path)
        {
            Ok(file) => return Ok((path, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    anyhow::bail!("Unable to create a unique diagnostic report")
}
fn persist_at(root: &Path, report: &Report) -> Result<()> {
    atomic_report(root, "latest-session.json", &encoded(report)?)
}
fn persist_failure_at(root: &Path, failure: &FailureRecord) -> Result<()> {
    validate_failure(failure)?;
    let bytes = serde_json::to_vec_pretty(failure)?;
    ensure!(
        bytes.len() as u64 <= MAX_REPORT_BYTES,
        "Diagnostic failure is too large"
    );
    atomic_report(root, "last-failure.json", &bytes)
}
fn atomic_report(root: &Path, name: &str, bytes: &[u8]) -> Result<()> {
    private_dir(root)?;
    let latest = root.join(name);
    if fs::symlink_metadata(&latest).is_ok() {
        drop(private_file(&latest)?);
    }
    let (temporary, mut file) = new_file(root, ".pending")?;
    let result = (|| {
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, &latest)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}
fn read_cached(root: &Path, name: &str) -> Result<Vec<u8>> {
    check_private_dir(root)?;
    let mut bytes = Vec::new();
    private_file(&root.join(name))?
        .take(MAX_REPORT_BYTES + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= MAX_REPORT_BYTES,
        "Diagnostic report is too large"
    );
    Ok(bytes)
}
fn retained_at(root: &Path) -> Result<FailureRecord> {
    let failure: FailureRecord = serde_json::from_slice(&read_cached(root, "last-failure.json")?)?;
    validate_failure(&failure)?;
    Ok(failure)
}
fn validate_version(version: &str) -> Result<()> {
    ensure!(
        !version.is_empty()
            && version.len() <= 32
            && version.chars().all(|c| c.is_ascii_digit() || c == '.'),
        "Invalid report version"
    );
    Ok(())
}
fn validate_identity(build: &BuildIdentity, environment: &Environment) -> Result<()> {
    for hash in [&build.app_sha256, &build.capture_helper_sha256]
        .into_iter()
        .flatten()
    {
        ensure!(
            hash.len() == 64 && hash.bytes().all(|c| c.is_ascii_hexdigit()),
            "Invalid binary fingerprint"
        );
    }
    for version in [
        &environment.kernel_release,
        &environment.nvidia_driver_version,
    ]
    .into_iter()
    .flatten()
    {
        ensure!(safe_version(version), "Invalid environment version");
    }
    Ok(())
}
fn validate_failure(failure: &FailureRecord) -> Result<()> {
    ensure!(
        failure.events.len() <= EVENT_LIMIT,
        "Diagnostic failure history is too large"
    );
    ensure!(
        failure
            .current
            .failure
            .as_ref()
            .is_some_and(|f| f.kind != FailureKind::SessionInterrupted),
        "Not a retained capture or USB failure"
    );
    validate_version(&failure.app_version)?;
    validate_identity(&failure.build, &failure.environment)
}
fn cached_at(root: &Path) -> Result<Report> {
    let bytes = read_cached(root, "latest-session.json")?;
    let mut report: Report = serde_json::from_slice(&bytes)?;
    ensure!(
        report.schema_version == 1
            && report.samples.len() <= SAMPLE_LIMIT
            && report.events.len() <= EVENT_LIMIT,
        "Unsupported diagnostic report"
    );
    validate_version(&report.app_version)?;
    validate_identity(&report.build, &report.environment)?;
    if let Some(failure) = &report.last_failure {
        validate_failure(failure)?;
    }
    // The failure file is committed first; a crash or failed latest write must not hide it.
    if let Ok(retained) = retained_at(root) {
        if report
            .last_failure
            .as_ref()
            .is_none_or(|previous| retained.captured_at_unix_ms >= previous.captured_at_unix_ms)
        {
            report.last_failure = Some(retained);
        }
    }
    report.source = ReportSource::CachedSession;
    report.stale = true;
    Ok(report)
}
/// Export a private unique report; no existing report is overwritten.
pub fn save_report(report: &Report) -> Result<PathBuf> {
    save_at(&state_root()?, report)
}
fn save_at(root: &Path, report: &Report) -> Result<PathBuf> {
    private_dir(root)?;
    let reports = root.join("reports");
    private_dir(&reports)?;
    let bytes = encoded(report)?;
    let (path, mut file) = new_file(&reports, "report")?;
    if let Err(error) = file.write_all(&bytes).and_then(|_| file.sync_all()) {
        let _ = fs::remove_file(&path);
        return Err(error.into());
    }
    Ok(path)
}
/// Read only the last persisted session; its current state is always explicitly stale.
pub fn cached_report() -> Result<Report> {
    cached_at(&state_root()?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, PermissionsExt};
    use std::time::Duration;

    fn root(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "nanoleaf-diagnostics-{name}-{}-{}",
            std::process::id(),
            now_ms()
        ));
        fs::DirBuilder::new().mode(0o700).create(&path).unwrap();
        path
    }
    fn status() -> Status {
        Status {
            running: true,
            message: "SECRET /home/person token=secret serial=private".into(),
            model: "SECRET".into(),
            backend: "SECRET".into(),
            response_clock: "SECRET".into(),
            ..Status::default()
        }
    }
    #[test]
    fn histories_are_bounded_sampled_and_redacted_by_construction() {
        let mut state = State::new();
        let mut status = status();
        for tick in 0..10000 {
            status.running = tick % 2 == 0;
            status.frames = tick;
            state.observe_at(&status, tick * 20, tick * 20);
        }
        let report = state.report(&status);
        assert_eq!(report.samples.len(), 120);
        assert_eq!(report.events.len(), 32);
        assert!(report
            .samples
            .windows(2)
            .all(|s| s[1].at_unix_ms - s[0].at_unix_ms >= 1000));
        assert!(!serde_json::to_string(&report).unwrap().contains("SECRET"));
        assert!(matches!(report.current.backend, Backend::Unknown));
    }
    #[test]
    fn failures_are_structured_and_events_are_not_repeated() {
        let mut state = State::new();
        let mut status = status();
        state.observe_at(&status, 0, 10);
        status.failure = Some(Failure::new(FailureKind::CaptureStalled, true));
        state.observe_at(&status, 20, 30);
        let event_count = state.events.len();
        for tick in 1..20 {
            state.observe_at(&status, tick * 20, tick * 20);
        }
        assert_eq!(state.events.len(), event_count);
        assert_eq!(state.report(&status).current.failure, status.failure);
        assert!(FailureKind::CaptureStalled.title().contains("Capture"));
    }
    #[test]
    fn reports_are_private_unique_and_cached_data_is_labelled() {
        let root = root("private");
        let report = State::new().report(&status());
        persist_at(&root, &report).unwrap();
        let latest = root.join("latest-session.json");
        assert_eq!(
            fs::metadata(&root).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(&latest).unwrap().permissions().mode() & 0o777,
            0o600
        );
        let cached = cached_at(&root).unwrap();
        assert!(cached.stale);
        assert_eq!(cached.source, ReportSource::CachedSession);
        assert!(!report.stale);
        assert_eq!(report.source, ReportSource::CurrentService);
        let first = save_at(&root, &report).unwrap();
        let second = save_at(&root, &report).unwrap();
        assert_ne!(first, second);
        assert_eq!(
            fs::metadata(first).unwrap().permissions().mode() & 0o777,
            0o600
        );
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn persistence_refuses_symlinks_and_keeps_foreign_files_untouched() {
        let root = root("symlinks");
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let victim = root.join("foreign");
        fs::write(&victim, "unchanged").unwrap();
        symlink(&victim, root.join("latest-session.json")).unwrap();
        let report = State::new().report(&status());
        assert!(persist_at(&root, &report).is_err());
        assert!(cached_at(&root).is_err());
        assert_eq!(fs::read_to_string(&victim).unwrap(), "unchanged");
        fs::remove_file(root.join("latest-session.json")).unwrap();
        symlink(&root, root.join("reports")).unwrap();
        assert!(save_at(&root, &report).is_err());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn failed_persistence_does_not_stop_the_recorder() {
        let root = root("actor");
        let state = Arc::new(Mutex::new(State::new()));
        let (wake, receiver) = mpsc::sync_channel(1);
        let (attempted, attempts) = mpsc::channel();
        let actor_state = state.clone();
        let actor_root = root.clone();
        let worker = std::thread::spawn(move || {
            let mut count = 0;
            actor(
                receiver,
                actor_state,
                Some(actor_root),
                0,
                |root, report| {
                    count += 1;
                    let result = if count == 1 {
                        Err(anyhow::anyhow!("Simulated write failure"))
                    } else {
                        persist_at(root, report)
                    };
                    let _ = attempted.send(result.is_ok());
                    result
                },
            );
        });
        let recorder = Recorder {
            state,
            wake: Some(wake),
            epoch: Instant::now(),
        };
        let mut status = status();
        recorder.observe(&status);
        assert!(!attempts.recv_timeout(Duration::from_secs(2)).unwrap());
        status.failure = Some(Failure::new(FailureKind::UsbDisconnected, true));
        recorder.observe(&status);
        assert!(attempts.recv_timeout(Duration::from_secs(2)).unwrap());
        assert_eq!(recorder.report(&status).current.failure, status.failure);
        assert_eq!(cached_at(&root).unwrap().current.failure, status.failure);
        status.running = false;
        recorder.observe(&status);
        assert!(attempts.recv_timeout(Duration::from_secs(2)).unwrap());
        drop(recorder);
        worker.join().unwrap();
        assert!(!cached_at(&root).unwrap().current.running);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn versions_fingerprints_and_cache_schema_are_safe_and_exact() {
        let root = root("metadata");
        let version = root.join("version");
        fs::write(&version, "6.18.2-1-cachyos\n").unwrap();
        assert_eq!(version_file(&version).as_deref(), Some("6.18.2-1-cachyos"));
        fs::write(&version, "version /home/private").unwrap();
        assert!(version_file(&version).is_none());
        fs::write(&version, "a".repeat(97)).unwrap();
        assert!(version_file(&version).is_none());
        fs::write(&version, "abc").unwrap();
        assert_eq!(
            hash_file(&version).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let report = State::new().report(&status());
        persist_at(&root, &report).unwrap();
        let mut value = serde_json::to_value(report).unwrap();
        value["arbitrary_error"] = serde_json::json!("SECRET");
        fs::write(
            root.join("latest-session.json"),
            serde_json::to_vec(&value).unwrap(),
        )
        .unwrap();
        assert!(cached_at(&root).is_err());
        value.as_object_mut().unwrap().remove("arbitrary_error");
        value["environment"]["kernel_release"] = serde_json::json!("SECRET /home/private");
        fs::write(
            root.join("latest-session.json"),
            serde_json::to_vec(&value).unwrap(),
        )
        .unwrap();
        assert!(cached_at(&root).is_err());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn identity_collection_never_blocks_observation_or_reports() {
        let (started, began) = mpsc::channel();
        let (release, wait) = mpsc::channel();
        let recorder = Recorder::with_identity(None, move || {
            started.send(()).unwrap();
            wait.recv().unwrap();
            (
                BuildIdentity {
                    app_sha256: Some("a".repeat(64)),
                    capture_helper_sha256: Some("b".repeat(64)),
                    identity_pending: false,
                },
                Environment::default(),
            )
        });
        began.recv_timeout(Duration::from_secs(2)).unwrap();
        let mut status = status();
        status.failure = Some(Failure::new(FailureKind::CaptureFailed, false));
        recorder.observe(&status);
        let report = recorder.report(&status);
        assert!(report.build.identity_pending);
        assert_eq!(report.current.failure, status.failure);
        assert!(!report.samples.is_empty());
        release.send(()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        while recorder.report(&status).build.identity_pending {
            assert!(
                Instant::now() < deadline,
                "Identity collector did not finish"
            );
            std::thread::sleep(Duration::from_millis(1));
        }
        let report = recorder.report(&status);
        assert_eq!(report.build.app_sha256, Some("a".repeat(64)));
        assert_eq!(report.build.capture_helper_sha256, Some("b".repeat(64)));
        assert_eq!(report.current.failure, status.failure);
    }
    #[test]
    fn unchanged_observation_wakes_only_periodically_and_cache_reads_create_nothing() {
        let mut state = State::new();
        let status = status();
        assert!(state.observe_at(&status, 0, 0));
        for tick in 1..250 {
            assert!(!state.observe_at(&status, tick * 20, tick * 20));
        }
        assert!(state.observe_at(&status, 5000, 5000));
        assert_eq!(state.events.len(), 1);
        let root = root("readonly");
        let absent = root.join("absent");
        assert!(cached_at(&absent).is_err());
        assert!(!absent.exists());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn retained_failure_survives_restart_with_original_identity_and_context() {
        let root = root("retained");
        let mut first = State::new();
        first.build = BuildIdentity {
            identity_pending: false,
            app_sha256: Some("a".repeat(64)),
            capture_helper_sha256: Some("b".repeat(64)),
        };
        first.environment.kernel_release = Some("6.18.2-old".into());
        let mut status = status();
        first.observe_at(&status, 0, 100);
        status.failure = Some(Failure {
            kind: FailureKind::CaptureStalled,
            at_unix_ms: 200,
            retrying: false,
        });
        first.observe_at(&status, 1000, 200);
        let failure = first.last_failure.clone().unwrap();
        persist_failure_at(&root, &failure).unwrap();
        persist_at(&root, &first.report(&status)).unwrap();
        let retained_bytes = fs::read(root.join("last-failure.json")).unwrap();
        let retained_inode = fs::metadata(root.join("last-failure.json")).unwrap().ino();
        let mut second = State::new();
        second.build = BuildIdentity {
            identity_pending: false,
            app_sha256: Some("c".repeat(64)),
            capture_helper_sha256: Some("d".repeat(64)),
        };
        second.load_retained(Some(retained_at(&root).unwrap()));
        status.failure = None;
        second.observe_at(&status, 0, 300);
        for tick in 1..1000 {
            second.observe_at(&status, tick * 20, 300 + tick * 20);
        }
        status.running = false;
        second.observe_at(&status, 30000, 30300);
        status.failure = Some(Failure::new(FailureKind::SessionInterrupted, false));
        second.observe_at(&status, 30020, 30320);
        let report = second.report(&status);
        assert_eq!(report.last_failure, Some(failure.clone()));
        assert_ne!(report.build, failure.build);
        assert_eq!(
            report
                .last_failure
                .as_ref()
                .unwrap()
                .environment
                .kernel_release
                .as_deref(),
            Some("6.18.2-old")
        );
        let mut saved_revision = 0;
        persist_state(
            &Mutex::new(second),
            &root,
            &mut persist_at,
            &mut saved_revision,
        );
        assert_eq!(
            fs::metadata(root.join("last-failure.json")).unwrap().ino(),
            retained_inode
        );
        assert_eq!(retained_at(&root).unwrap(), failure);
        assert_eq!(
            fs::read(root.join("last-failure.json")).unwrap(),
            retained_bytes
        );
        assert_eq!(cached_at(&root).unwrap().last_failure, report.last_failure);
        let mut tampered = serde_json::to_value(report).unwrap();
        tampered["last_failure"]["build"]["app_sha256"] = serde_json::json!("SECRET");
        fs::write(
            root.join("latest-session.json"),
            serde_json::to_vec(&tampered).unwrap(),
        )
        .unwrap();
        assert!(cached_at(&root).is_err());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn failure_during_identity_loading_wins_over_older_retained_failure() {
        let mut state = State::new();
        let mut status = status();
        status.failure = Some(Failure::new(FailureKind::UsbDisconnected, true));
        state.observe_at(&status, 0, 100);
        let current = state.last_failure.clone().unwrap();
        let mut previous = current.clone();
        previous.captured_at_unix_ms = 1;
        previous.build.app_sha256 = Some("a".repeat(64));
        state.load_retained(Some(previous));
        assert_eq!(state.last_failure, Some(current));
        state.complete_identity(
            BuildIdentity {
                identity_pending: false,
                app_sha256: Some("b".repeat(64)),
                capture_helper_sha256: None,
            },
            Environment::default(),
        );
        assert_eq!(
            state.last_failure.as_ref().unwrap().build.app_sha256,
            Some("b".repeat(64))
        );
        assert!(!state.last_failure.as_ref().unwrap().build.identity_pending);
    }
    #[test]
    fn cached_export_merges_a_newer_failure_even_when_latest_session_write_lagged() {
        let root = root("lagged");
        let mut state = State::new();
        let mut status = status();
        state.observe_at(&status, 0, 100);
        persist_at(&root, &state.report(&status)).unwrap();
        status.failure = Some(Failure::new(FailureKind::CaptureEnded, false));
        state.observe_at(&status, 1000, 200);
        persist_failure_at(&root, state.last_failure.as_ref().unwrap()).unwrap();
        assert_eq!(cached_at(&root).unwrap().last_failure, state.last_failure);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn maximum_histories_and_numeric_widths_fit_the_export_limit() {
        let mut state = State::new();
        state.build = BuildIdentity {
            identity_pending: false,
            app_sha256: Some("f".repeat(64)),
            capture_helper_sha256: Some("f".repeat(64)),
        };
        state.environment.kernel_release = Some("9".repeat(96));
        state.environment.nvidia_driver_version = Some("9".repeat(96));
        let mut status = status();
        status.frames = u64::MAX;
        status.dropped_frames = u64::MAX;
        status.missed_deadlines = u64::MAX;
        status.reconnects = u64::MAX;
        status.capture_ms = f64::MAX;
        status.processing_ms = f64::MAX;
        status.usb_ms = f64::MAX;
        status.response_ms = f64::MAX;
        status.effective_fps = f64::MAX;
        for tick in 0..150 {
            status.failure = Some(Failure {
                kind: FailureKind::UsbInitialization,
                at_unix_ms: u64::MAX - tick,
                retrying: true,
            });
            state.observe_at(&status, tick * 1000, u64::MAX - tick);
        }
        let mut report = state.report(&status);
        report.app_version = "9".repeat(32);
        report.last_failure.as_mut().unwrap().app_version = "9".repeat(32);
        assert_eq!(report.samples.len(), SAMPLE_LIMIT);
        assert_eq!(report.events.len(), EVENT_LIMIT);
        assert_eq!(
            report.last_failure.as_ref().unwrap().events.len(),
            EVENT_LIMIT
        );
        let bytes = encoded(&report).unwrap();
        assert!(bytes.len() as u64 <= MAX_REPORT_BYTES);
        let root = root("max-size");
        let path = save_at(&root, &report).unwrap();
        let exported: Report = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(exported.samples.len(), SAMPLE_LIMIT);
        assert_eq!(exported.last_failure.unwrap().events.len(), EVENT_LIMIT);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn unsafe_numbers_are_omitted_and_oversized_cache_is_rejected() {
        let mut status = status();
        status.capture_ms = f64::NAN;
        status.usb_ms = f64::INFINITY;
        let report = State::new().report(&status);
        assert_eq!(report.current.capture_ms, None);
        assert_eq!(report.current.usb_ms, None);
        let root = root("oversize");
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(root.join("latest-session.json"))
            .unwrap();
        file.set_len(MAX_REPORT_BYTES + 1).unwrap();
        assert!(cached_at(&root).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
