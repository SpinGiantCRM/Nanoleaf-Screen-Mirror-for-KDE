//! One owner for capture, processing, strip output and preview/reconnect lifecycle.
use crate::{
    config::Store,
    device::Strip,
    pipeline::ProcessingTimes,
    worker::{Prepared, Producer},
};
use anyhow::{bail, ensure, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    os::unix::{
        fs::{FileTypeExt, MetadataExt, OpenOptionsExt, PermissionsExt},
        net::{UnixListener, UnixStream},
    },
    path::{Path, PathBuf},
    sync::{mpsc, Arc, Mutex},
    time::{Duration, Instant},
};
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
pub enum Control {
    Status,
    #[serde(skip)]
    FrameReady,
    Start,
    Stop,
    Reload,
    Quit,
    Preview {
        rgb: [u8; 3],
        zone: Option<usize>,
    },
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Status {
    pub running: bool,
    pub preview: bool,
    pub message: String,
    pub model: String,
    pub manual_zones: usize,
    pub reported_zones: usize,
    pub frames: u64,
    #[serde(default)]
    pub predicted_frames: u64,
    #[serde(default)]
    pub prediction_enabled: bool,
    #[serde(default)]
    pub reused_source_packets: u64,
    #[serde(default)]
    pub last_source_reused: bool,
    pub missed_deadlines: u64,
    pub dropped_frames: u64,
    pub capture_ms: f64,
    pub processing_ms: f64,
    pub usb_ms: f64,
    #[serde(default)]
    pub usb_transaction: Option<crate::device::TransactionTimes>,
    pub response_ms: f64,
    /// Capture work to the final HID write returning, excluding the ACK wait.
    /// Host completion is not proof of the device's emitted-light timing.
    #[serde(default)]
    pub response_to_write_ms: Option<f64>,
    /// Parent latest-slot residence before USB starts; excludes capture/IPC.
    #[serde(default)]
    pub prepared_queue_ms: Option<f64>,
    #[serde(default)]
    pub response_summary: Option<crate::response::ResponseSummary>,
    #[serde(default)]
    pub response_clock: String,
    #[serde(default)]
    pub source_presentation_age_ms: Option<f64>,
    #[serde(default)]
    pub capture_stages: Option<crate::worker::CaptureStages>,
    pub effective_fps: f64,
    pub startup_ms: f64,
    pub reconnects: u64,
    pub backend: String,
    pub priority: crate::priority::PriorityStatus,
}
#[derive(Clone)]
pub struct Paths {
    pub root: PathBuf,
    pub socket: PathBuf,
}
impl Paths {
    /// Hold the service lease throughout an install/rollback. A stale socket
    /// from a crashed service is recoverable; a live tray must be quit first.
    pub fn maintenance(&self) -> Result<File> {
        let guard = lease(&self.root.join("service.lock"))
            .context("Quit the native tray before changing installed versions")?;
        if let Ok(meta) = fs::symlink_metadata(&self.socket) {
            ensure!(
                meta.file_type().is_socket(),
                "Unexpected native control socket file"
            );
            fs::remove_file(&self.socket)?;
        }
        Ok(guard)
    }
    pub fn new() -> Result<Self> {
        let root = PathBuf::from(
            std::env::var_os("XDG_RUNTIME_DIR")
                .context("A desktop runtime directory is required")?,
        )
        .join("nanoleaf-native");
        if !root.exists() {
            std::fs::DirBuilder::new().mode(0o700).create(&root)?;
        }
        let meta = fs::symlink_metadata(&root)?;
        ensure!(
            meta.is_dir()
                && !meta.file_type().is_symlink()
                && meta.uid() == rustix::process::geteuid().as_raw()
                && meta.mode() & 0o077 == 0,
            "Unsafe native runtime directory"
        );
        Ok(Self {
            socket: root.join("control.sock"),
            root,
        })
    }
}
use std::os::unix::fs::DirBuilderExt;
fn lease(path: &Path) -> Result<File> {
    let f = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(path)?;
    rustix::fs::flock(&f, rustix::fs::FlockOperation::NonBlockingLockExclusive)
        .context("Another strip session is already active")?;
    Ok(f)
}
pub fn send(control: &Control) -> Result<Status> {
    send_at(&Paths::new()?.socket, control)
}
pub fn send_at(socket: &Path, control: &Control) -> Result<Status> {
    let mut stream =
        UnixStream::connect(socket).context("The native tray service is not running")?;
    stream.set_read_timeout(Some(Duration::from_secs(1)))?;
    stream.set_write_timeout(Some(Duration::from_secs(1)))?;
    serde_json::to_writer(&mut stream, control)?;
    stream.write_all(b"\n")?;
    stream.shutdown(std::net::Shutdown::Write)?;
    let mut data = String::new();
    stream.take(16384).read_to_string(&mut data)?;
    Ok(serde_json::from_str(&data)?)
}
fn listener(socket: &Path, tx: mpsc::Sender<Control>, status: Arc<Mutex<Status>>) -> Result<()> {
    if socket.exists() {
        fs::remove_file(socket)?;
    }
    let listener = UnixListener::bind(socket)?;
    fs::set_permissions(socket, fs::Permissions::from_mode(0o600))?;
    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
            let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
            let mut reader = BufReader::new(stream);
            let mut line = String::new();
            if reader.by_ref().take(4097).read_line(&mut line).is_err() || line.len() > 4096 {
                continue;
            }
            if let Ok(control) = serde_json::from_str::<Control>(&line) {
                // Finish the reply before dispatching Quit: the actor can exit
                // immediately, otherwise truncating JSON on the listener thread.
                if let Ok(value) = status.lock() {
                    if let Ok(bytes) = serde_json::to_vec(&*value) {
                        let _ = reader.get_mut().write_all(&bytes);
                    }
                }
                if !matches!(control, Control::Status) {
                    let _ = tx.send(control);
                }
            }
        }
    });
    Ok(())
}
fn fallback_running() -> bool {
    fs::read_dir("/proc")
        .into_iter()
        .flatten()
        .flatten()
        .any(|entry| {
            let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
                return false;
            };
            if pid == std::process::id() {
                return false;
            }
            let Ok(data) = fs::read(entry.path().join("cmdline")) else {
                return false;
            };
            let args: Vec<_> = data
                .split(|&b| b == 0)
                .filter_map(|v| std::str::from_utf8(v).ok())
                .collect();
            args.iter().any(|arg| {
                Path::new(arg).file_name().is_some_and(|name| {
                    name == "nanoleaf-kde-sync" || name == "nanoleaf-kde-sync-doctor"
                })
            }) || args.windows(2).any(|v| {
                v[0] == "-m" && (v[1] == "nanoleaf_sync" || v[1].starts_with("nanoleaf_sync."))
            })
        })
}
pub(crate) fn acquire_output(paths: &Paths) -> Result<File> {
    ensure!(
        !fallback_running(),
        "The Python fallback is running; stop it before native LED output"
    );
    lease(&paths.root.join("strip.lock"))
}
fn publish(shared: &Arc<Mutex<Status>>, status: &Status) {
    if let Ok(mut s) = shared.lock() {
        *s = status.clone();
    }
}
fn open_strip(store: &Store) -> Result<Strip> {
    let c = &store.config;
    let s = Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    Ok(s)
}
pub fn run(path: &Path, start: bool, tray: bool) -> Result<()> {
    run_inner(path, start, tray, None, None)
}
pub fn run_profile(path: &Path, seconds: f64) -> Result<()> {
    ensure!(
        seconds.is_finite() && (1.0..=30.0).contains(&seconds),
        "Live probe duration must be 1 to 30 seconds"
    );
    run_inner(
        path,
        true,
        true,
        Some(Duration::from_secs_f64(seconds)),
        None,
    )
}
pub fn run_stream_profile(path: &Path, seconds: f64) -> Result<()> {
    ensure!(
        seconds.is_finite() && (1.0..=30.0).contains(&seconds),
        "Live probe duration must be 1 to 30 seconds"
    );
    run_inner(
        path,
        true,
        true,
        Some(Duration::from_secs_f64(seconds)),
        Some("xdg-portal"),
    )
}
fn run_inner(
    path: &Path,
    start: bool,
    tray: bool,
    profile: Option<Duration>,
    backend: Option<&str>,
) -> Result<()> {
    let mut start_time = Instant::now();
    let paths = Paths::new()?;
    let _instance = lease(&paths.root.join("service.lock"))?;
    let mut store = Store::load(path)?;
    if let Some(backend) = backend {
        store.config.capture_backend = backend.into();
    }
    let (tx, rx) = mpsc::channel();
    let mut state = Status {
        manual_zones: store.config.device_zone_count,
        message: "Stopped".into(),
        backend: if store.config.capture_backend == "xdg-portal" {
            "xdg-portal / requesting stream".into()
        } else {
            "kwin-dbus (SDR display-referred)".into()
        },
        priority: crate::priority::apply(&store.config.performance_priority),
        ..Default::default()
    };
    let shared = Arc::new(Mutex::new(state.clone()));
    listener(&paths.socket, tx.clone(), shared.clone())?;
    let mut tray_message = state.message.clone();
    let _tray = if tray {
        match crate::tray::spawn(path.into(), tx.clone()) {
            Ok(h) => Some(h),
            Err(e) => {
                state.message =
                    format!("Tray unavailable: {e}. Settings and controls remain available.");
                None
            }
        }
    } else {
        None
    };
    if let Some(duration) = profile {
        let tx = tx.clone();
        std::thread::spawn(move || {
            std::thread::sleep(duration);
            let _ = tx.send(Control::Quit);
        });
    }
    let mut original_controller: Option<(Vec<u8>, Vec<u8>)> = None;
    let mut samples = Vec::new();
    let mut restored = false;
    let mut output_owner = None;
    let mut strip: Option<Strip> = None;
    let mut capture: Option<Producer> = None;
    let mut watchdog = CaptureWatchdog::default();
    let mut preview = None;
    let mut predictor = crate::prediction::Predictor::default();
    let mut usb_history = std::collections::VecDeque::<Duration>::new();
    let mut responses = crate::response::Responses::default();
    let mut response_epoch = Instant::now();
    let mut retry = Instant::now();
    let mut deadline = Instant::now();
    let mut fps_epoch = Instant::now();
    let mut epoch_frames = 0;
    if start || store.config.start_on_launch {
        tx.send(Control::Start)?;
    }
    loop {
        let timeout = if state.running || state.preview {
            deadline.saturating_duration_since(Instant::now())
        } else {
            Duration::from_secs(30)
        };
        if let Ok(command) = rx.recv_timeout(timeout) {
            let mut ready = false;
            match command {
                Control::FrameReady => {
                    if capture.is_none() || !state.running {
                        continue;
                    }
                    ready = true;
                }
                Control::Status => {}
                Control::Quit => {
                    state.response_summary = Some(responses.summary());
                    // Release capture before reporting: a slow stdout consumer
                    // must never keep screen sharing or hardware ownership alive.
                    state.running = false;
                    state.preview = false;
                    state.effective_fps = 0.0;
                    state.message = "Stopped".into();
                    drop(capture.take());
                    predictor.reset();
                    usb_history.clear();
                    watchdog.reset();
                    if let Some(s) = &mut strip {
                        let _ = s.black();
                        if let Some((power, brightness)) = &original_controller {
                            restored = s.restore_controller(power, brightness);
                        }
                    }
                    drop(strip.take());
                    publish(&shared, &state);
                    break;
                }
                Control::Stop => {
                    state.response_summary = Some(responses.summary());
                    predictor.reset();
                    usb_history.clear();
                    watchdog.reset();
                    state.running = false;
                    state.preview = false;
                    state.effective_fps = 0.0;
                    preview = None;
                    if let Some(s) = &mut strip {
                        let _ = s.black();
                    }
                    strip = None;
                    output_owner = None;
                    capture = None;
                    state.message = "Stopped".into();
                }
                Control::Reload => match Store::load(path) {
                    Ok(s) => {
                        if state.running {
                            if let Err(e) = crate::pipeline::validate_mirroring(&s.config) {
                                state.message = format!("Settings not applied: {e}");
                                publish(&shared, &state);
                                continue;
                            }
                        }
                        if let Some(strip) = &mut strip {
                            let _ = strip.black();
                        }
                        predictor.reset();
                        usb_history.clear();
                        watchdog.reset();
                        store = s;
                        responses = crate::response::Responses::default();
                        state.response_summary = None;
                        state.prepared_queue_ms = None;
                        response_epoch = Instant::now();
                        if let Some(backend) = backend {
                            store.config.capture_backend = backend.into();
                        }
                        state.priority = crate::priority::apply(&store.config.performance_priority);
                        strip = None;
                        capture = None;
                        preview = None;
                        state.preview = false;
                        if !state.running {
                            output_owner = None;
                        }
                        state.manual_zones = store.config.device_zone_count;
                        state.message = "Settings applied".into();
                        retry = Instant::now();
                    }
                    Err(e) => state.message = format!("Settings not applied: {e}"),
                },
                Control::Start => {
                    if let Err(e) = crate::pipeline::validate_mirroring(&store.config) {
                        state.message = e.to_string();
                        publish(&shared, &state);
                        continue;
                    }
                    let ready = if output_owner.is_some() {
                        true
                    } else {
                        match acquire_output(&paths) {
                            Ok(owner) => {
                                output_owner = Some(owner);
                                true
                            }
                            Err(e) => {
                                state.message = e.to_string();
                                false
                            }
                        }
                    };
                    if ready && !state.running {
                        responses = crate::response::Responses::default();
                        state.response_summary = None;
                        state.prepared_queue_ms = None;
                        response_epoch = Instant::now();
                        start_time = Instant::now();
                        state.running = true;
                        state.preview = false;
                        preview = None;
                        predictor.reset();
                        usb_history.clear();
                        watchdog.reset();
                        state.frames = 0;
                        state.predicted_frames = 0;
                        state.missed_deadlines = 0;
                        fps_epoch = Instant::now();
                        epoch_frames = 0;
                        retry = Instant::now();
                        deadline = Instant::now();
                        state.message = "Starting".into();
                    }
                }
                Control::Preview { rgb, zone } => {
                    if zone.is_some_and(|n| n >= store.config.device_zone_count) {
                        state.message = "Preview index exceeds the manual strip count".into();
                    } else if output_owner.is_some() || {
                        match acquire_output(&paths) {
                            Ok(owner) => {
                                output_owner = Some(owner);
                                true
                            }
                            Err(e) => {
                                state.message = e.to_string();
                                false
                            }
                        }
                    } {
                        predictor.reset();
                        usb_history.clear();
                        watchdog.reset();
                        state.running = false;
                        state.preview = true;
                        capture = None;
                        preview = Some((rgb, zone, Instant::now() + Duration::from_secs(10)));
                        deadline = Instant::now();
                        retry = Instant::now();
                    }
                }
            }
            publish(&shared, &state);
            if let Some(handle) = &_tray {
                if tray_message != state.message {
                    handle.update(|t| t.message = state.message.clone());
                    tray_message = state.message.clone();
                }
            }
            if !ready {
                continue;
            }
        }
        if !state.running && !state.preview {
            continue;
        }
        if let Some((_, _, until)) = preview {
            if Instant::now() >= until {
                tx.send(Control::Stop)?;
                continue;
            }
        }
        if strip.is_none() {
            if Instant::now() < retry {
                deadline = retry;
                continue;
            }
            match open_strip(&store) {
                Ok(mut s) => {
                    let initialized = (|| -> Result<()> {
                        if profile.is_some() && original_controller.is_none() {
                            let power = s.request(0x06, &[])?;
                            let brightness = s.request(0x08, &[])?;
                            ensure!(
                                power.len() == 1
                                    && power[0] <= 1
                                    && brightness.len() == 1
                                    && brightness[0] <= 100,
                                "Invalid controller state; cannot safely run live probe"
                            );
                            original_controller = Some((power, brightness));
                        }
                        if profile.is_some() {
                            // Reapply the bounded test limit after every reconnect.
                            s.request(0x09, &[10])?;
                        }
                        if store.config.auto_turn_on || profile.is_some() {
                            s.on()?;
                        }
                        Ok(())
                    })();
                    if let Err(e) = initialized {
                        state.message = format!("Strip initialization recovery: {e}");
                        retry = Instant::now() + Duration::from_secs(2);
                        deadline = retry;
                        publish(&shared, &state);
                        continue;
                    }
                    state.model = s.model.clone();
                    state.reported_zones = s.reported_count;
                    strip = Some(s);
                    responses = crate::response::Responses::default();
                    state.response_summary = None;
                    state.prepared_queue_ms = None;
                    response_epoch = Instant::now();
                    state.reconnects += 1;
                    state.message = "Strip connected".into();
                }
                Err(e) => {
                    state.message = format!("Waiting for strip: {e}");
                    retry = Instant::now() + Duration::from_secs(2);
                    deadline = retry;
                    publish(&shared, &state);
                    continue;
                }
            }
        }
        let frame_start = Instant::now();
        let mut ready_at = None;
        let work = (|| -> Result<Option<Prepared>> {
            if let Some((rgb, zone, _)) = preview {
                let mut colors = vec![[0; 3]; store.config.device_zone_count];
                if let Some(index) = zone {
                    colors[index] = rgb;
                } else {
                    colors.fill(rgb);
                }
                return Ok(Some(Prepared {
                    unquantized_rgb: None,
                    colors,
                    times: ProcessingTimes::default(),
                    capture_ms: 0.0,
                    started: frame_start,
                    backend: "Exclusive setup preview".into(),
                    parity_verified: false,
                    highlight_cache: (0, 0),
                    source_reused: false,
                    response_clock: "preview",
                    source_pts_ns: None,
                    capture_stages: None,
                }));
            }
            if capture.is_none() {
                watchdog.start(Instant::now(), store.config.fps);
                capture = Some(Producer::spawn(store.config.clone(), tx.clone()));
            }
            match capture.as_ref().unwrap().take_with_ready_time() {
                Some((Ok(out), at)) => {
                    ready_at = Some(at);
                    Ok(Some(out))
                }
                Some((Err(error), _)) => bail!("{error}"),
                None => Ok(None),
            }
        })();
        let mut predicted = false;
        let work = match work {
            Ok(None) => match predictor.predict_with_budget(
                &store.config,
                Instant::now(),
                usb_history
                    .iter()
                    .copied()
                    .max()
                    .unwrap_or(Duration::from_millis(250)),
            ) {
                Some(colors) => {
                    predicted = true;
                    Ok(Some(Prepared {
                        unquantized_rgb: None,
                        colors,
                        times: ProcessingTimes::default(),
                        capture_ms: 0.0,
                        started: Instant::now(),
                        backend: state.backend.clone(),
                        parity_verified: false,
                        highlight_cache: (0, 0),
                        source_reused: false,
                        response_clock: "prediction",
                        source_pts_ns: None,
                        capture_stages: None,
                    }))
                }
                None => {
                    if watchdog.expired(Instant::now()) {
                        Err(anyhow::anyhow!(
                            "Capture stalled; no fresh frame within the recovery deadline"
                        ))
                    } else {
                        deadline = predictor
                            .deadline(&store.config)
                            .unwrap_or_else(|| {
                                watchdog
                                    .deadline()
                                    .unwrap_or_else(|| Instant::now() + Duration::from_secs(30))
                            })
                            .min(
                                watchdog
                                    .deadline()
                                    .unwrap_or_else(|| Instant::now() + Duration::from_secs(30)),
                            );
                        continue;
                    }
                }
            },
            other => other,
        };
        match work {
            Ok(None) => unreachable!(),
            Ok(Some(prepared)) => {
                let Prepared {
                    mut colors,
                    unquantized_rgb,
                    times,
                    capture_ms,
                    started,
                    backend,
                    parity_verified: _,
                    highlight_cache: _,
                    source_reused,
                    response_clock,
                    source_pts_ns,
                    capture_stages,
                } = prepared;
                state.backend = backend;
                if store.config.blue_noise_dither && !state.preview {
                    if let Some(rgb) = unquantized_rgb {
                        colors = crate::pipeline::quantize_acknowledged(&rgb, state.frames);
                    }
                }
                let usb_start = Instant::now();
                let queue_ms = ready_at
                    .map(|at| usb_start.saturating_duration_since(at).as_secs_f64() * 1000.0);
                let result = strip.as_mut().unwrap().frame(&colors);
                state.usb_ms = usb_start.elapsed().as_secs_f64() * 1000.0;
                state.usb_transaction = strip
                    .as_ref()
                    .and_then(|s| s.last_frame_transaction.clone());
                match result {
                    Ok(()) => {
                        usb_history.push_back(usb_start.elapsed());
                        if usb_history.len() > 32 {
                            usb_history.pop_front();
                        }
                        state.frames += 1;
                        state.last_source_reused = source_reused;
                        if source_reused {
                            state.reused_source_packets += 1;
                        }
                        if predicted {
                            state.predicted_frames += 1;
                        } else if !state.preview {
                            watchdog.frame(Instant::now());
                            if source_reused {
                                predictor.reset();
                            } else {
                                predictor.observe(&colors, Instant::now());
                            }
                            state.capture_ms = capture_ms;
                            state.processing_ms = times.total_ms;
                            state.response_ms = started.elapsed().as_secs_f64() * 1000.0;
                            state.response_to_write_ms = state
                                .usb_transaction
                                .as_ref()
                                .and_then(|t| t.write_completed)
                                .map(|written| {
                                    written.saturating_duration_since(started).as_secs_f64()
                                        * 1000.0
                                });
                            state.response_clock = response_clock.into();
                            state.prepared_queue_ms = queue_ms;
                            if let (Some(queue_ms), Some(to_write_ms)) =
                                (queue_ms, state.response_to_write_ms)
                            {
                                responses.record(
                                    crate::response::Sample {
                                        capture_ms,
                                        processing_ms: times.total_ms,
                                        queue_ms,
                                        usb_ms: state.usb_ms,
                                        to_write_ms,
                                        to_ack_ms: state.response_ms,
                                    },
                                    source_reused,
                                );
                            }
                            state.capture_stages = capture_stages;
                            state.source_presentation_age_ms = source_pts_ns.map(|pts| {
                                let now =
                                    rustix::time::clock_gettime(rustix::time::ClockId::Monotonic);
                                ((now.tv_sec as i128 * 1_000_000_000 + now.tv_nsec as i128)
                                    - pts as i128) as f64
                                    / 1_000_000.0
                            });
                        }
                        if let Some(producer) = &capture {
                            producer.acknowledge(&colors);
                            state.dropped_frames = producer.dropped();
                            state.missed_deadlines = producer.missed();
                        }
                        state.message = if state.preview {
                            "Preview · mirroring paused".into()
                        } else {
                            "Mirroring".into()
                        };
                        if state.frames == 1 {
                            state.startup_ms = start_time.elapsed().as_secs_f64() * 1000.0;
                        }
                    }
                    Err(e) => {
                        state.response_summary = Some(responses.summary());
                        predictor.reset();
                        usb_history.clear();
                        watchdog.reset();
                        state.message = format!("USB recovery: {e}");
                        strip = None;
                        capture = None;
                        retry = Instant::now() + Duration::from_secs(2);
                    }
                }
            }
            Err(e) => {
                state.response_summary = Some(responses.summary());
                predictor.reset();
                usb_history.clear();
                watchdog.reset();
                state.message = format!("Capture/colour recovery: {e}");
                if let Some(s) = &mut strip {
                    let _ = s.black();
                }
                capture = None;
                if store.config.capture_backend == "xdg-portal" {
                    // Sharing denial/revocation is not permission to acquire the
                    // screen again or switch to another capture interface.
                    if let (Some(s), Some((power, brightness))) = (&mut strip, &original_controller)
                    {
                        restored = s.restore_controller(power, brightness);
                    }
                    state.running = false;
                    state.effective_fps = 0.0;
                    strip = None;
                    output_owner = None;
                    state.message =
                        format!("Screen sharing stopped: {e}. Start to request it again.");
                }
                deadline = Instant::now() + Duration::from_secs(2);
                publish(&shared, &state);
                continue;
            }
        }
        if response_epoch.elapsed() >= Duration::from_secs(1) {
            state.response_summary = Some(responses.summary());
            response_epoch = Instant::now();
        }
        if fps_epoch.elapsed() >= Duration::from_secs(1) {
            state.effective_fps =
                (state.frames - epoch_frames) as f64 / fps_epoch.elapsed().as_secs_f64();
            fps_epoch = Instant::now();
            epoch_frames = state.frames;
        }
        let period = Duration::from_secs_f64(1.0 / store.config.fps as f64);
        deadline += period;
        if deadline < Instant::now() {
            state.missed_deadlines += 1;
            deadline = Instant::now();
        }
        if strip.is_none() {
            deadline = retry;
        } else if state.preview {
            deadline = Instant::now() + Duration::from_millis(250);
        } else if capture.is_some() {
            deadline = predictor
                .deadline(&store.config)
                .unwrap_or_else(|| {
                    watchdog
                        .deadline()
                        .unwrap_or_else(|| Instant::now() + Duration::from_secs(30))
                })
                .min(
                    watchdog
                        .deadline()
                        .unwrap_or_else(|| Instant::now() + Duration::from_secs(30)),
                );
        }
        state.prediction_enabled = crate::prediction::enabled(&store.config);
        if profile.is_some() {
            samples.push(state.clone());
        }
        publish(&shared, &state);
        if let Some(handle) = &_tray {
            if tray_message != state.message {
                handle.update(|t| t.message = state.message.clone());
                tray_message = state.message.clone();
            }
        }
    }
    if let Some((power, brightness)) = &original_controller {
        if !restored {
            if let Ok(mut s) = open_strip(&store) {
                let _ = s.black();
                restored = s.restore_controller(power, brightness);
            }
        }
    }
    drop(capture.take());
    drop(strip.take());
    drop(output_owner);
    let _ = fs::remove_file(&paths.socket);
    if profile.is_some() {
        let proc = std::fs::read_to_string("/proc/self/status").unwrap_or_default();
        let memory: Vec<_> = proc
            .lines()
            .filter(|l| {
                l.starts_with("VmRSS:") || l.starts_with("VmHWM:") || l.starts_with("Threads:")
            })
            .collect();
        println!(
            "{}",
            serde_json::json!({"scope":"Native tray/service, live native-resolution SDR capture, colour pipeline and real USB ACK. Backend is recorded per sample. No optical colour/response measurement.","status":state,"samples":samples,"controller_power_brightness_restored":restored,"memory":memory})
        );
    }
    if profile.is_some() {
        ensure!(
            !samples.is_empty() && samples.iter().any(|s| s.frames > 0),
            "Live probe produced no acknowledged frames"
        );
        ensure!(
            restored,
            "Live probe could not verify controller power/brightness restoration"
        );
    }
    Ok(())
}
pub fn require_service() -> Result<()> {
    if !Paths::new()?.socket.exists() {
        bail!("Start the native tray before controlling the strip");
    }
    Ok(())
}

/// First permission acquisition has a bounded 120-second allowance. Once a
/// captured or healthy unchanged-source frame is acknowledged, silence expires
/// at two seconds or three target periods. Prediction never refreshes it. Reuse
/// is emitted only from the live permission-bound PipeWire loop, not a timer in
/// the parent that could hide a stalled capture child.
#[derive(Default)]
pub struct CaptureWatchdog {
    deadline: Option<Instant>,
    period: Duration,
}
impl CaptureWatchdog {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn start(&mut self, now: Instant, fps: u32) {
        self.period = Duration::from_secs_f64(3.0 / fps.max(1) as f64).max(Duration::from_secs(2));
        self.deadline = Some(now + Duration::from_secs(120));
    }
    pub fn frame(&mut self, now: Instant) {
        self.deadline = Some(now + self.period);
    }
    pub fn deadline(&self) -> Option<Instant> {
        self.deadline
    }
    pub fn expired(&self, now: Instant) -> bool {
        self.deadline.is_some_and(|d| now >= d)
    }
}
