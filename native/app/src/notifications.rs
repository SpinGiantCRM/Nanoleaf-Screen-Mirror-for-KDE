//! Desktop notices for structured mirroring failures; never restarts automatically.
//! Status updates only replace a tiny latest-state slot. All D-Bus traffic runs
//! on one owned worker, with bounded calls and no capture or USB access.
use crate::{
    diagnostics::{Failure, FailureKind},
    service::{Control, Status},
};
use anyhow::{Context, Result};
use futures_lite::{future, StreamExt};
use std::{
    collections::HashMap,
    sync::{mpsc, Arc, Condvar, Mutex},
    thread::JoinHandle,
    time::Duration,
};

const CALL_TIMEOUT: Duration = Duration::from_millis(500);
const SIGNAL_TICK: Duration = Duration::from_millis(100);
const NAME: &str = "org.freedesktop.Notifications";
const PATH: &str = "/org/freedesktop/Notifications";

#[derive(Default)]
struct State {
    failure: Option<Failure>,
    generation: u64,
    stop: bool,
}
#[derive(Default)]
struct Shared {
    state: Mutex<State>,
    changed: Condvar,
}

/// Best-effort notifications: unavailable notification services never prevent
/// service startup, capture, shutdown, or manual controls.
pub struct Notifier {
    shared: Arc<Shared>,
    worker: Option<JoinHandle<()>>,
}
impl Notifier {
    pub fn spawn(tx: mpsc::Sender<Control>) -> Self {
        Self::start(tx, None)
    }
    fn start(tx: mpsc::Sender<Control>, address: Option<String>) -> Self {
        let shared = Arc::new(Shared::default());
        let worker_state = shared.clone();
        let worker = std::thread::Builder::new()
            .name("nanoleaf-notifications".into())
            .spawn(move || work(&worker_state, &tx, address.as_deref()))
            .ok();
        Self { shared, worker }
    }
    pub fn update(&self, status: &Status) {
        // Session lock/suspend notices would appear at the wrong time and are
        // deliberately suppressed. No status message or raw error is copied.
        let failure = status
            .failure
            .as_ref()
            .filter(|failure| !matches!(failure.kind, FailureKind::SessionInterrupted));
        if let Ok(mut state) = self.shared.state.lock() {
            if state.failure.as_ref() != failure {
                state.failure = failure.cloned();
                state.generation = state.generation.wrapping_add(1);
                self.shared.changed.notify_one();
            }
        }
    }
}
impl Drop for Notifier {
    fn drop(&mut self) {
        if let Ok(mut state) = self.shared.state.lock() {
            state.stop = true;
            self.shared.changed.notify_one();
        }
        // No detached thread survives the owner. In-flight connection/Notify
        // and CloseNotification calls are bounded; a live notice wakes at 100ms.
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn restart_allowed(failure: &Failure) -> bool {
    !failure.retrying
        && matches!(
            failure.kind,
            FailureKind::CaptureStalled | FailureKind::CaptureEnded | FailureKind::CaptureFailed
        )
}
fn body(failure: &Failure) -> &'static str {
    if failure.retrying {
        match failure.kind {
            FailureKind::UsbDisconnected | FailureKind::UsbInitialization =>
                "Waiting for the strip to reconnect. Check its USB connection; mirroring is reconnecting automatically.",
            _ => "Waiting for screen capture to reconnect. Mirroring is retrying automatically.",
        }
    } else {
        failure.kind.body()
    }
}
fn current(shared: &Shared, generation: u64) -> bool {
    shared
        .state
        .lock()
        .is_ok_and(|state| !state.stop && state.generation == generation)
}
fn work(shared: &Shared, tx: &mpsc::Sender<Control>, address: Option<&str>) {
    let mut seen = 0;
    loop {
        let Ok(mut state) = shared.state.lock() else {
            return;
        };
        while !state.stop && state.generation == seen {
            let Ok(next) = shared.changed.wait(state) else {
                return;
            };
            state = next;
        }
        if state.stop {
            return;
        }
        seen = state.generation;
        let failure = state.failure.clone();
        drop(state);
        if let Some(failure) = failure {
            // Failure is best-effort and is attempted once per episode. A missing
            // daemon cannot turn per-frame updates into repeated bus traffic.
            let _ = future::block_on(show(shared, tx, address, seen, &failure));
        }
    }
}
struct LiveNotice {
    proxy: zbus::Proxy<'static>,
    signals: zbus::proxy::SignalStream<'static>,
    id: u32,
}
async fn open(address: Option<&str>, failure: &Failure) -> Result<LiveNotice> {
    let builder = if let Some(address) = address {
        zbus::connection::Builder::address(address)?
    } else {
        zbus::connection::Builder::session()?
    };
    let connection = builder.method_timeout(CALL_TIMEOUT).build().await?;
    let dbus = zbus::fdo::DBusProxy::new(&connection).await?;
    let owner = dbus.get_name_owner(NAME.try_into()?).await?;
    // Pin the unique daemon owner: an unrelated daemon after owner replacement
    // must not reuse an old notification ID to trigger a stale action.
    let proxy = zbus::Proxy::new_owned(connection.clone(), owner, PATH, NAME).await?;
    let signals = proxy.receive_all_signals().await?;
    let actions = if restart_allowed(failure) {
        vec!["restart", "Restart mirroring"]
    } else {
        vec![]
    };
    let hints = HashMap::from([(
        "desktop-entry",
        zbus::zvariant::Value::from("org.spingiantcrm.NanoleafNative"),
    )]);
    let id = proxy
        .call(
            "Notify",
            &(
                "Nanoleaf Screen Mirror",
                0_u32,
                "org.spingiantcrm.NanoleafNative",
                failure.kind.title(),
                body(failure),
                actions,
                hints,
                15_000_i32,
            ),
        )
        .await?;
    Ok(LiveNotice { proxy, signals, id })
}
async fn bounded<T>(operation: impl std::future::Future<Output = Result<T>>) -> Result<T> {
    future::race(operation, async {
        async_io::Timer::after(CALL_TIMEOUT).await;
        anyhow::bail!("Notification service timed out")
    })
    .await
}
async fn show(
    shared: &Shared,
    tx: &mpsc::Sender<Control>,
    address: Option<&str>,
    generation: u64,
    failure: &Failure,
) -> Result<()> {
    if !current(shared, generation) {
        return Ok(());
    }
    let mut notice = bounded(open(address, failure)).await?;
    let mut acted = false;
    while current(shared, generation) {
        enum Event {
            Signal(Option<zbus::message::Message>),
            Tick,
        }
        let event = future::race(
            async { Event::Signal(notice.signals.next().await) },
            async {
                async_io::Timer::after(SIGNAL_TICK).await;
                Event::Tick
            },
        )
        .await;
        if matches!(event, Event::Signal(None)) {
            break;
        }
        if let Event::Signal(Some(message)) = event {
            let header = message.header();
            let member = header.member().map(|member| member.as_str());
            if member == Some("NotificationClosed") {
                if message
                    .body()
                    .deserialize::<(u32, u32)>()
                    .is_ok_and(|(id, _)| id == notice.id)
                {
                    // Dismissed/expired IDs may later belong to another notice.
                    return Ok(());
                }
                continue;
            }
            if member != Some("ActionInvoked") {
                continue;
            }
            let Ok((id, action)) = message.body().deserialize::<(u32, String)>() else {
                continue;
            };
            if id != notice.id || action != "restart" || acted || !restart_allowed(failure) {
                continue;
            }
            // Recheck the latest state at action delivery, not just at Notify.
            // Hold this tiny lock through enqueueing to order against updates.
            // The service checks the carried episode again when it dequeues the
            // request, so an already queued Stop also invalidates this action.
            if let Ok(state) = shared.state.lock() {
                if !state.stop
                    && state.generation == generation
                    && state.failure.as_ref() == Some(failure)
                {
                    acted = true;
                    let _ = tx.send(Control::RestartFailure {
                        failure: failure.clone(),
                    });
                }
            }
        }
    }
    bounded(async {
        notice
            .proxy
            .call::<_, _, ()>("CloseNotification", &(notice.id,))
            .await
            .context("Close notification")
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::diagnostics::{Failure, FailureKind};
    use std::{
        collections::HashMap,
        io::{BufRead, BufReader},
        process::{Child, Command, Stdio},
        sync::{
            atomic::{AtomicU32, Ordering},
            Arc,
        },
        time::{Duration, Instant},
    };

    #[derive(Debug)]
    enum Received {
        Notice {
            id: u32,
            app: String,
            icon: String,
            summary: String,
            body: String,
            actions: Vec<String>,
            timeout: i32,
        },
        Close(u32),
    }
    struct FakeNotifications {
        next: Arc<AtomicU32>,
        events: mpsc::Sender<Received>,
    }
    #[zbus::interface(name = "org.freedesktop.Notifications")]
    impl FakeNotifications {
        #[allow(clippy::too_many_arguments)]
        fn notify(
            &self,
            app_name: &str,
            _replaces_id: u32,
            app_icon: &str,
            summary: &str,
            body: &str,
            actions: Vec<String>,
            _hints: HashMap<String, zbus::zvariant::OwnedValue>,
            expire_timeout: i32,
        ) -> u32 {
            let id = self.next.fetch_add(1, Ordering::Relaxed);
            self.events
                .send(Received::Notice {
                    id,
                    app: app_name.into(),
                    icon: app_icon.into(),
                    summary: summary.into(),
                    body: body.into(),
                    actions,
                    timeout: expire_timeout,
                })
                .unwrap();
            id
        }
        fn close_notification(&self, id: u32) {
            self.events.send(Received::Close(id)).unwrap();
        }
    }
    struct Bus(Child);
    impl Drop for Bus {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    struct Fixture {
        _bus: Bus,
        address: String,
        server: zbus::blocking::Connection,
        events: mpsc::Receiver<Received>,
    }
    impl Fixture {
        fn new(with_service: bool) -> Self {
            let mut bus = Bus(Command::new("dbus-daemon")
                .args(["--session", "--nofork", "--print-address"])
                .stdout(Stdio::piped())
                .spawn()
                .unwrap());
            let mut address = String::new();
            BufReader::new(bus.0.stdout.take().unwrap())
                .read_line(&mut address)
                .unwrap();
            let address = address.trim().to_owned();
            let (events, rx) = mpsc::channel();
            let builder = zbus::blocking::connection::Builder::address(address.as_str()).unwrap();
            let builder = if with_service {
                builder.name("org.freedesktop.Notifications").unwrap()
            } else {
                builder
            };
            let server = builder
                .serve_at(
                    "/org/freedesktop/Notifications",
                    FakeNotifications {
                        next: Arc::new(AtomicU32::new(1)),
                        events,
                    },
                )
                .unwrap()
                .build()
                .unwrap();
            Self {
                _bus: bus,
                address,
                server,
                events: rx,
            }
        }
        fn notifier(&self) -> (Notifier, mpsc::Receiver<Control>) {
            let (tx, rx) = mpsc::channel();
            (Notifier::start(tx, Some(self.address.clone())), rx)
        }
        fn receive(&self) -> Received {
            self.events
                .recv_timeout(Duration::from_secs(3))
                .expect("notification worker did not deliver expected message")
        }
        fn action(&self, id: u32, action: &str) {
            self.server
                .emit_signal(
                    None::<&str>,
                    "/org/freedesktop/Notifications",
                    "org.freedesktop.Notifications",
                    "ActionInvoked",
                    &(id, action),
                )
                .unwrap();
        }
    }
    fn failed(kind: FailureKind, at_unix_ms: u64, retrying: bool) -> Status {
        Status {
            failure: Some(Failure {
                kind,
                at_unix_ms,
                retrying,
            }),
            message: "SECRET token=private /home/person".into(),
            ..Status::default()
        }
    }

    // Removing notification delivery, deduplication, or action validation breaks this
    // real private-bus test. It never sends notifications to the desktop bus.
    #[test]
    #[ignore = "Operator integration: private dbus-daemon, no desktop notifications"]
    fn private_bus_notifies_once_and_only_current_user_action_restarts() {
        let fixture = Fixture::new(true);
        let (notifier, controls) = fixture.notifier();
        let status = failed(FailureKind::CaptureStalled, 123, false);
        notifier.update(&status);
        let id = match fixture.receive() {
            Received::Notice {
                id,
                app,
                icon,
                summary,
                body,
                actions,
                timeout,
            } => {
                assert_eq!(app, "Nanoleaf Screen Mirror");
                assert!(!icon.is_empty());
                assert!(summary.to_lowercase().contains("capture"));
                assert!(body.contains("Restart"));
                assert!(!body.contains("SECRET"));
                assert_eq!(actions, ["restart", "Restart mirroring"]);
                assert!(timeout > 0);
                id
            }
            other => panic!("expected Notify, got {other:?}"),
        };
        for _ in 0..1000 {
            notifier.update(&status);
        }
        assert!(
            fixture
                .events
                .recv_timeout(Duration::from_millis(250))
                .is_err(),
            "one episode must produce one notice"
        );
        assert!(
            controls.try_recv().is_err(),
            "notification delivery must never restart output"
        );
        fixture.action(id, "unknown");
        assert!(controls.recv_timeout(Duration::from_millis(150)).is_err());
        fixture.action(id, "restart");
        match controls.recv_timeout(Duration::from_secs(2)).unwrap() {
            Control::RestartFailure { failure } => assert_eq!(Some(failure), status.failure),
            other => panic!("expected conditional episode restart, got {other:?}"),
        }
        fixture.action(id, "restart");
        assert!(
            controls.recv_timeout(Duration::from_millis(150)).is_err(),
            "an action must be consumed once"
        );
        notifier.update(&Status::default());
        assert!(matches!(fixture.receive(), Received::Close(closed) if closed == id));
        fixture.action(id, "restart");
        assert!(
            controls.recv_timeout(Duration::from_millis(150)).is_err(),
            "a manual Stop invalidates old actions"
        );
        // A fresh unconsumed action is also invalidated immediately by Stop,
        // including while the worker is still waiting for its next bus event.
        notifier.update(&failed(FailureKind::CaptureEnded, 124, false));
        let fresh = match fixture.receive() {
            Received::Notice { id, .. } => id,
            other => panic!("expected fresh notice, got {other:?}"),
        };
        notifier.update(&Status::default());
        fixture.action(fresh, "restart");
        assert!(controls.recv_timeout(Duration::from_millis(150)).is_err());
        assert!(matches!(fixture.receive(), Received::Close(closed) if closed == fresh));
        drop(notifier);
    }

    #[test]
    #[ignore = "Operator integration: private dbus-daemon, no desktop notifications"]
    fn private_bus_retry_notices_have_no_restart_and_recovery_closes_them() {
        let fixture = Fixture::new(true);
        let (notifier, controls) = fixture.notifier();
        notifier.update(&failed(FailureKind::UsbDisconnected, 10, true));
        let id = match fixture.receive() {
            Received::Notice {
                id, actions, body, ..
            } => {
                assert!(actions.is_empty());
                assert!(body.to_lowercase().contains("reconnect"));
                id
            }
            other => panic!("expected retry notice, got {other:?}"),
        };
        fixture.action(id, "restart");
        assert!(controls.recv_timeout(Duration::from_millis(150)).is_err());
        notifier.update(&Status {
            running: true,
            ..Status::default()
        });
        assert!(matches!(fixture.receive(), Received::Close(closed) if closed == id));
        notifier.update(&failed(FailureKind::SessionInterrupted, 20, false));
        assert!(fixture
            .events
            .recv_timeout(Duration::from_millis(250))
            .is_err());
        drop(notifier);
    }

    #[test]
    #[ignore = "Operator integration: private dbus-daemon, no desktop notifications"]
    fn private_bus_old_episode_action_cannot_restart_new_failure_and_drop_closes() {
        let fixture = Fixture::new(true);
        let (notifier, controls) = fixture.notifier();
        notifier.update(&failed(FailureKind::CaptureEnded, 1, false));
        let first = match fixture.receive() {
            Received::Notice { id, .. } => id,
            other => panic!("{other:?}"),
        };
        notifier.update(&failed(FailureKind::CaptureFailed, 2, false));
        assert!(matches!(fixture.receive(), Received::Close(id) if id == first));
        let second = match fixture.receive() {
            Received::Notice { id, .. } => id,
            other => panic!("{other:?}"),
        };
        fixture.action(first, "restart");
        assert!(controls.recv_timeout(Duration::from_millis(150)).is_err());
        let started = Instant::now();
        drop(notifier);
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(matches!(fixture.receive(), Received::Close(id) if id == second));
        assert!(controls.try_recv().is_err());
    }

    #[test]
    #[ignore = "Operator integration: private dbus-daemon, no desktop notifications"]
    fn private_bus_missing_service_does_not_block_updates_or_shutdown() {
        let fixture = Fixture::new(false);
        let (notifier, controls) = fixture.notifier();
        let status = failed(FailureKind::UsbInitialization, 1, true);
        let started = Instant::now();
        for _ in 0..10000 {
            notifier.update(&status);
        }
        assert!(started.elapsed() < Duration::from_secs(1));
        std::thread::sleep(Duration::from_millis(200));
        let started = Instant::now();
        drop(notifier);
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(controls.try_recv().is_err());
        assert!(fixture.events.try_recv().is_err());
    }

    #[test]
    #[ignore = "Operator integration: private dbus-daemon, no desktop notifications"]
    fn private_bus_dismissed_notice_cannot_restart_if_its_id_is_reused() {
        let fixture = Fixture::new(true);
        let (notifier, controls) = fixture.notifier();
        notifier.update(&failed(FailureKind::CaptureFailed, 50, false));
        let id = match fixture.receive() {
            Received::Notice { id, .. } => id,
            other => panic!("expected notice, got {other:?}"),
        };
        fixture
            .server
            .emit_signal(None::<&str>, PATH, NAME, "NotificationClosed", &(id, 2_u32))
            .unwrap();
        fixture.action(id, "restart");
        assert!(
            controls.recv_timeout(Duration::from_millis(250)).is_err(),
            "dismissed notification IDs must not remain armed"
        );
        drop(notifier);
    }
}
