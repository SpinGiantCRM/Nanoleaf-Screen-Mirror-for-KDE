//! KDE session interruptions stop output and require an explicit restart.
//! No Lock/Suspend/Inhibit call is made. In particular, no pre-suspend cleanup
//! completion is promised: logind can suspend before a non-inhibiting client
//! runs. Its resume signal independently invalidates the old capture session.
use crate::service::Control;
use anyhow::Result;
use futures_lite::{future, StreamExt};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Condvar, Mutex,
    },
    time::{Duration, Instant},
};

#[derive(Clone, Copy)]
enum Source {
    Lock = 0,
    Sleep = 1,
}
impl Source {
    fn spec(self) -> (&'static str, &'static str, &'static str, &'static str) {
        match self {
            Self::Lock => (
                "org.freedesktop.ScreenSaver",
                "/ScreenSaver",
                "org.freedesktop.ScreenSaver",
                "ActiveChanged",
            ),
            Self::Sleep => (
                "org.freedesktop.login1",
                "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager",
                "PrepareForSleep",
            ),
        }
    }
}

#[derive(Default)]
struct State {
    active: [Option<bool>; 2],
    attempted: [bool; 2],
}
impl State {
    fn blocked(&self) -> Option<&'static str> {
        if self.active[0] == Some(true) {
            Some("Screen locked; unlock and choose Start to mirror again")
        } else if self.active[1] == Some(true) {
            Some("System preparing for sleep; choose Start after resuming")
        } else if self.active.contains(&None) {
            Some("Desktop session monitoring unavailable; waiting to reconnect before Start")
        } else {
            None
        }
    }
    fn update(&mut self, source: Source, value: Option<bool>, signal: bool) -> bool {
        let index = source as usize;
        let previous = self.active[index];
        self.active[index] = value;
        self.attempted[index] = true;
        // Do not auto-start on unlock, reconnection, or resume. A resume must
        // stop even when PrepareForSleep(true) was missed during suspension.
        (value == Some(true) && previous != value)
            || (value.is_none() && previous.is_some())
            || (signal && matches!(source, Source::Sleep))
    }
}

struct Shared {
    state: Mutex<State>,
    ready: Condvar,
    stop: AtomicBool,
    tx: mpsc::Sender<Control>,
}
impl Shared {
    fn update(&self, source: Source, value: Option<bool>, signal: bool) {
        if let Ok(mut state) = self.state.lock() {
            let was_blocked = state.blocked().is_some();
            if state.update(source, value, signal) {
                let _ = self.tx.send(Control::SessionInterrupted);
            }
            if was_blocked && state.blocked().is_none() {
                let _ = self.tx.send(Control::SessionReady);
            }
            self.ready.notify_all();
        }
    }
}

pub(crate) struct Guard(Arc<Shared>);
impl Guard {
    pub fn new(tx: mpsc::Sender<Control>) -> Self {
        Self::start(tx, None)
    }
    fn start(tx: mpsc::Sender<Control>, address: Option<String>) -> Self {
        let shared = Arc::new(Shared {
            state: Mutex::new(State::default()),
            ready: Condvar::new(),
            stop: AtomicBool::new(false),
            tx,
        });
        let worker = shared.clone();
        std::thread::spawn(move || {
            future::block_on(async {
                future::zip(
                    watch(&worker, Source::Lock, address.as_deref()),
                    watch(&worker, Source::Sleep, address.as_deref()),
                )
                .await;
            })
        });
        // Initial queries run concurrently and have bounded method timeouts.
        // A missing service keeps the tray usable but output fails closed until
        // reconnect. Ordinary daily Start is not lost to a startup thread race.
        if let Ok(state) = shared.state.lock() {
            let _ = shared
                .ready
                .wait_timeout_while(state, Duration::from_secs(3), |s| {
                    !s.attempted.iter().all(|v| *v)
                });
        }
        Self(shared)
    }
    pub fn blocked(&self) -> Option<&'static str> {
        self.0
            .state
            .lock()
            .map(|s| s.blocked())
            .unwrap_or(Some("Desktop session monitoring failed; restart the app"))
    }
}
impl Drop for Guard {
    fn drop(&mut self) {
        self.0.stop.store(true, Ordering::Release);
    }
}

async fn watch(shared: &Shared, source: Source, address: Option<&str>) {
    while !shared.stop.load(Ordering::Acquire) {
        let _ = connected(shared, source, address).await;
        if shared.stop.load(Ordering::Acquire) {
            break;
        }
        shared.update(source, None, false);
        // Bound cancellation/retry latency without waking or polling per frame.
        for _ in 0..8 {
            if shared.stop.load(Ordering::Acquire) {
                return;
            }
            async_io::Timer::after(Duration::from_millis(250)).await;
        }
    }
}

async fn current(proxy: &zbus::Proxy<'_>, source: Source) -> Result<bool> {
    Ok(match source {
        Source::Lock => proxy.call("GetActive", &()).await?,
        Source::Sleep => proxy.get_property("PreparingForSleep").await?,
    })
}

async fn connected(shared: &Shared, source: Source, address: Option<&str>) -> Result<()> {
    let builder = if let Some(address) = address {
        zbus::connection::Builder::address(address)?
    } else {
        match source {
            Source::Lock => zbus::connection::Builder::session()?,
            Source::Sleep => zbus::connection::Builder::system()?,
        }
    };
    let connection = builder
        .method_timeout(Duration::from_secs(2))
        .build()
        .await?;
    let (name, path, interface, signal) = source.spec();
    // Disable property caching: the periodic query must detect lost owners or
    // missed changes. PreparingForSleep does not emit PropertiesChanged.
    let proxy = zbus::proxy::Builder::<zbus::Proxy<'_>>::new(&connection)
        .destination(name)?
        .path(path)?
        .interface(interface)?
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()
        .await?;
    // Subscribe before querying so a transition in the initialization window
    // remains queued and cannot leave a stale unlocked state indefinitely.
    let mut signals = proxy.receive_signal(signal).await?;
    shared.update(source, Some(current(&proxy, source).await?), false);
    let mut refreshed = Instant::now();
    while !shared.stop.load(Ordering::Acquire) {
        enum Event {
            Signal(Option<zbus::message::Message>),
            Tick,
        }
        let event = future::race(async { Event::Signal(signals.next().await) }, async {
            async_io::Timer::after(Duration::from_millis(250)).await;
            Event::Tick
        })
        .await;
        match event {
            Event::Signal(Some(message)) => {
                let (active,): (bool,) = message.body().deserialize()?;
                shared.update(source, Some(active), true);
            }
            Event::Signal(None) => anyhow::bail!("Session monitor disconnected"),
            Event::Tick => {}
        }
        if refreshed.elapsed() >= Duration::from_secs(2) {
            shared.update(source, Some(current(&proxy, source).await?), false);
            refreshed = Instant::now();
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct FakeLock(Arc<AtomicBool>);
    #[zbus::interface(name = "org.freedesktop.ScreenSaver")]
    impl FakeLock {
        fn get_active(&self) -> bool {
            self.0.load(Ordering::Acquire)
        }
    }
    struct FakeSleep(Arc<AtomicBool>);
    #[zbus::interface(name = "org.freedesktop.login1.Manager")]
    impl FakeSleep {
        #[zbus(property)]
        fn preparing_for_sleep(&self) -> bool {
            self.0.load(Ordering::Acquire)
        }
    }

    #[test]
    #[ignore = "Operator integration: private dbus-daemon; never locks or sleeps the desktop"]
    fn private_bus_signals_owner_loss_and_recovery() {
        use std::{
            io::{BufRead, BufReader},
            process::{Command, Stdio},
        };
        struct Bus(std::process::Child);
        impl Drop for Bus {
            fn drop(&mut self) {
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
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
        let locked = Arc::new(AtomicBool::new(false));
        let sleeping = Arc::new(AtomicBool::new(false));
        let server = zbus::blocking::connection::Builder::address(address.as_str())
            .unwrap()
            .name("org.freedesktop.ScreenSaver")
            .unwrap()
            .name("org.freedesktop.login1")
            .unwrap()
            .serve_at("/ScreenSaver", FakeLock(locked.clone()))
            .unwrap()
            .serve_at("/org/freedesktop/login1", FakeSleep(sleeping.clone()))
            .unwrap()
            .build()
            .unwrap();
        let (tx, rx) = mpsc::channel();
        let guard = Guard::start(tx, Some(address));
        assert!(guard.blocked().is_none());
        assert!(matches!(
            rx.recv_timeout(Duration::from_secs(1)).unwrap(),
            Control::SessionReady
        ));
        let emit = |source: Source, active| {
            let (_, path, interface, member) = source.spec();
            server
                .emit_signal(None::<&str>, path, interface, member, &(active,))
                .unwrap();
        };
        let interrupted = || {
            assert!(matches!(
                rx.recv_timeout(Duration::from_secs(4)).unwrap(),
                Control::SessionInterrupted
            ))
        };
        let available = || {
            let until = Instant::now() + Duration::from_secs(6);
            while guard.blocked().is_some() && Instant::now() < until {
                std::thread::sleep(Duration::from_millis(10));
            }
            assert!(guard.blocked().is_none());
        };
        locked.store(true, Ordering::Release);
        emit(Source::Lock, true);
        interrupted();
        assert!(guard.blocked().unwrap().contains("locked"));
        locked.store(false, Ordering::Release);
        emit(Source::Lock, false);
        available();
        assert!(matches!(
            rx.recv_timeout(Duration::from_secs(1)).unwrap(),
            Control::SessionReady
        ));
        assert!(rx.try_recv().is_err(), "Unlock must not start output");
        // Resume without the earlier prepare signal still invalidates capture.
        emit(Source::Sleep, false);
        interrupted();
        assert!(guard.blocked().is_none());
        sleeping.store(true, Ordering::Release);
        emit(Source::Sleep, true);
        interrupted();
        assert!(guard.blocked().is_some());
        sleeping.store(false, Ordering::Release);
        emit(Source::Sleep, false);
        interrupted();
        available();
        assert!(matches!(
            rx.recv_timeout(Duration::from_secs(1)).unwrap(),
            Control::SessionReady
        ));
        server.release_name("org.freedesktop.ScreenSaver").unwrap();
        interrupted();
        assert!(guard.blocked().unwrap().contains("unavailable"));
        server.request_name("org.freedesktop.ScreenSaver").unwrap();
        available();
        assert!(matches!(
            rx.recv_timeout(Duration::from_secs(1)).unwrap(),
            Control::SessionReady
        ));
        assert!(
            rx.try_recv().is_err(),
            "Monitor recovery must not start output"
        );
        let shared = Arc::downgrade(&guard.0);
        drop(guard);
        let until = Instant::now() + Duration::from_secs(3);
        while shared.strong_count() > 0 && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(
            shared.strong_count(),
            0,
            "Watchers must release connections after shutdown"
        );
    }
    #[test]
    fn missing_monitor_or_locked_session_cannot_start_output() {
        let mut s = State::default();
        assert!(s.blocked().is_some());
        assert!(!s.update(Source::Lock, Some(false), false));
        assert!(s.blocked().is_some());
        assert!(!s.update(Source::Sleep, Some(false), false));
        assert!(s.blocked().is_none());
        assert!(s.update(Source::Lock, Some(true), true));
        assert!(s.blocked().unwrap().contains("locked"));
        assert!(!s.update(Source::Lock, Some(true), false));
        assert!(!s.update(Source::Lock, Some(false), true));
        assert!(s.blocked().is_none());
    }
    #[test]
    fn resume_invalidates_old_capture_even_if_before_sleep_was_missed() {
        let mut s = State::default();
        s.update(Source::Lock, Some(false), false);
        s.update(Source::Sleep, Some(false), false);
        assert!(s.update(Source::Sleep, Some(false), true));
        assert!(s.blocked().is_none());
        assert!(s.update(Source::Sleep, Some(true), true));
        assert!(s.blocked().is_some());
        assert!(s.update(Source::Sleep, Some(false), true));
        assert!(s.blocked().is_none());
    }
    #[test]
    fn monitor_loss_stops_once_and_recovery_never_requests_start() {
        let mut s = State::default();
        s.update(Source::Lock, Some(false), false);
        s.update(Source::Sleep, Some(false), false);
        assert!(s.update(Source::Lock, None, false));
        assert!(s.blocked().is_some());
        assert!(!s.update(Source::Lock, None, false));
        assert!(!s.update(Source::Lock, Some(false), false));
        assert!(s.blocked().is_none());
    }
}
