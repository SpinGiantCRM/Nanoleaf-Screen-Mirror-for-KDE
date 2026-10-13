//! KDE-compatible file selection through the existing Rust D-Bus client.
//! The GUI stays responsive; cancellation closes the request/connection.
use anyhow::{ensure, Context, Result};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{mpsc, Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use zbus::{
    blocking::{Connection, Proxy},
    zvariant::{OwnedObjectPath, OwnedValue, Value},
};
const DEST: &str = "org.freedesktop.portal.Desktop";
#[derive(Default)]
struct State {
    request: Option<(Connection, String)>,
    cancelled: bool,
}
type RequestState = Arc<Mutex<State>>;
pub struct Picker {
    result: mpsc::Receiver<Result<Option<PathBuf>>>,
    request: RequestState,
}
impl Picker {
    pub fn start(save_name: Option<String>) -> Self {
        Self::start_with_address(save_name, None)
    }
    fn start_with_address(save_name: Option<String>, address: Option<String>) -> Self {
        let (tx, result) = mpsc::sync_channel(1);
        let request = RequestState::default();
        let shared = request.clone();
        std::thread::spawn(move || {
            let _ = tx.send(select(save_name, shared, address));
        });
        Self { result, request }
    }
    pub fn result(&self) -> Option<Result<Option<PathBuf>>> {
        self.result.try_recv().ok()
    }
}
impl Drop for Picker {
    fn drop(&mut self) {
        if let Ok(mut state) = self.request.lock() {
            state.cancelled = true;
            if let Some((connection, path)) = state.request.take() {
                std::thread::spawn(move || {
                    if let Ok(proxy) = Proxy::new_owned(
                        connection.clone(),
                        DEST,
                        path,
                        "org.freedesktop.portal.Request",
                    ) {
                        let _: zbus::Result<()> = proxy.call("Close", &());
                    }
                    let _ = connection.close();
                });
            }
        }
    }
}
fn select(
    save_name: Option<String>,
    state: RequestState,
    address: Option<String>,
) -> Result<Option<PathBuf>> {
    let builder = if let Some(address) = address {
        zbus::blocking::connection::Builder::address(address.as_str())?
    } else {
        zbus::blocking::connection::Builder::session()?
    };
    let connection = builder.method_timeout(Duration::from_secs(5)).build()?;
    let sender = connection
        .unique_name()
        .context("Portal client has no unique name")?
        .as_str()
        .trim_start_matches(':')
        .replace('.', "_");
    let token = format!(
        "nanoleaf_{}_{}",
        std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
    );
    let path = format!("/org/freedesktop/portal/desktop/request/{sender}/{token}");
    {
        let mut state = state
            .lock()
            .map_err(|_| anyhow::anyhow!("File chooser state unavailable"))?;
        if state.cancelled {
            return Ok(None);
        }
        state.request = Some((connection.clone(), path.clone()));
    }
    let request = Proxy::new_owned(
        connection.clone(),
        DEST,
        path.clone(),
        "org.freedesktop.portal.Request",
    )?;
    let mut replies = request.receive_signal("Response")?;
    let portal = Proxy::new_owned(
        connection,
        DEST,
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.FileChooser",
    )?;
    let filters = vec![(
        "Calibration profile".to_string(),
        vec![(0_u32, "*.json".to_string())],
    )];
    let mut options = HashMap::from([
        ("handle_token", Value::from(token.as_str())),
        ("modal", Value::from(true)),
        ("filters", Value::new(filters)),
    ]);
    if let Some(name) = &save_name {
        options.insert("current_name", Value::from(name.as_str()));
    }
    let handle: OwnedObjectPath = portal.call(
        if save_name.is_some() {
            "SaveFile"
        } else {
            "OpenFile"
        },
        &(
            "",
            if save_name.is_some() {
                "Export measured LED profile"
            } else {
                "Import measured LED profile"
            },
            options,
        ),
    )?;
    ensure!(
        handle.as_str() == path,
        "Unexpected file chooser request path"
    );
    let message = replies
        .next()
        .context("File chooser closed without a response")?;
    let (code, values): (u32, HashMap<String, OwnedValue>) = message.body().deserialize()?;
    if code == 1 {
        return Ok(None);
    }
    ensure!(code == 0, "File chooser failed");
    let uris: Vec<String> = values
        .get("uris")
        .context("File chooser returned no file")?
        .try_clone()?
        .try_into()?;
    ensure!(uris.len() == 1, "Choose one profile file");
    let uri = url::Url::parse(&uris[0])?;
    Ok(Some(uri.to_file_path().map_err(|_| {
        anyhow::anyhow!("Choose a local profile file")
    })?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader},
        process::{Child, Command, Stdio},
        sync::atomic::{AtomicUsize, Ordering},
        time::Instant,
    };
    #[derive(Clone)]
    struct Plan {
        code: u32,
        uris: Vec<String>,
        hold: bool,
    }
    struct Fake {
        plan: Arc<Mutex<Plan>>,
        opened: Arc<AtomicUsize>,
        closed: Arc<AtomicUsize>,
    }
    struct Request {
        closed: Arc<AtomicUsize>,
    }
    #[zbus::interface(name = "org.freedesktop.portal.Request")]
    impl Request {
        fn close(&self) {
            self.closed.fetch_add(1, Ordering::SeqCst);
        }
    }
    impl Fake {
        async fn respond(
            &self,
            options: HashMap<String, OwnedValue>,
            header: zbus::message::Header<'_>,
            connection: &zbus::Connection,
        ) -> zbus::fdo::Result<OwnedObjectPath> {
            let handle: String = options
                .get("handle_token")
                .unwrap()
                .try_clone()
                .unwrap()
                .try_into()
                .unwrap();
            let sender = header
                .sender()
                .unwrap()
                .as_str()
                .trim_start_matches(':')
                .replace('.', "_");
            let path: OwnedObjectPath =
                format!("/org/freedesktop/portal/desktop/request/{sender}/{handle}")
                    .try_into()
                    .unwrap();
            connection
                .object_server()
                .at(
                    path.clone(),
                    Request {
                        closed: self.closed.clone(),
                    },
                )
                .await?;
            self.opened.fetch_add(1, Ordering::SeqCst);
            let plan = self.plan.lock().unwrap().clone();
            if !plan.hold {
                let values = HashMap::from([("uris", Value::new(plan.uris))]);
                // Deliver before method return: catches subscribe-after-call races.
                connection
                    .emit_signal(
                        None::<&str>,
                        path.clone(),
                        "org.freedesktop.portal.Request",
                        "Response",
                        &(plan.code, values),
                    )
                    .await?;
            }
            Ok(path)
        }
    }
    #[zbus::interface(name = "org.freedesktop.portal.FileChooser")]
    impl Fake {
        async fn open_file(
            &self,
            _parent: &str,
            _title: &str,
            options: HashMap<String, OwnedValue>,
            #[zbus(header)] header: zbus::message::Header<'_>,
            #[zbus(connection)] connection: &zbus::Connection,
        ) -> zbus::fdo::Result<OwnedObjectPath> {
            self.respond(options, header, connection).await
        }
        async fn save_file(
            &self,
            _parent: &str,
            _title: &str,
            options: HashMap<String, OwnedValue>,
            #[zbus(header)] header: zbus::message::Header<'_>,
            #[zbus(connection)] connection: &zbus::Connection,
        ) -> zbus::fdo::Result<OwnedObjectPath> {
            assert!(options.contains_key("current_name"));
            self.respond(options, header, connection).await
        }
    }
    struct Bus(Child);
    impl Drop for Bus {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    fn until(mut check: impl FnMut() -> bool) {
        let deadline = Instant::now() + Duration::from_secs(3);
        while !check() {
            assert!(Instant::now() < deadline, "Portal fixture timed out");
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    fn answer(picker: &Picker) -> Result<Option<PathBuf>> {
        let mut result = None;
        until(|| {
            result = picker.result();
            result.is_some()
        });
        result.unwrap()
    }
    #[test]
    fn chooser_handles_early_replies_local_uris_denial_and_cancellation() {
        let child = Command::new("dbus-daemon")
            .args(["--session", "--nofork", "--print-address=1"])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let mut bus = Bus(child);
        let mut address = String::new();
        BufReader::new(bus.0.stdout.take().unwrap())
            .read_line(&mut address)
            .unwrap();
        let address = address.trim().to_string();
        let plan = Arc::new(Mutex::new(Plan {
            code: 0,
            uris: vec!["file:///tmp/calibration%20profile.json".into()],
            hold: false,
        }));
        let opened = Arc::new(AtomicUsize::new(0));
        let closed = Arc::new(AtomicUsize::new(0));
        let server = zbus::blocking::connection::Builder::address(address.as_str())
            .unwrap()
            .name(DEST)
            .unwrap()
            .serve_at(
                "/org/freedesktop/portal/desktop",
                Fake {
                    plan: plan.clone(),
                    opened: opened.clone(),
                    closed: closed.clone(),
                },
            )
            .unwrap()
            .build()
            .unwrap();
        let picker = Picker::start_with_address(None, Some(address.clone()));
        assert_eq!(
            answer(&picker).unwrap(),
            Some(PathBuf::from("/tmp/calibration profile.json"))
        );
        drop(picker);
        let picker =
            Picker::start_with_address(Some("measured.json".into()), Some(address.clone()));
        assert!(answer(&picker).unwrap().is_some());
        drop(picker);
        plan.lock().unwrap().code = 1;
        let picker = Picker::start_with_address(None, Some(address.clone()));
        assert!(answer(&picker).unwrap().is_none());
        drop(picker);
        plan.lock().unwrap().code = 0;
        plan.lock().unwrap().uris = vec!["https://example.invalid/profile.json".into()];
        let picker = Picker::start_with_address(None, Some(address.clone()));
        assert!(answer(&picker).is_err());
        drop(picker);
        plan.lock().unwrap().uris =
            vec!["file:///tmp/one.json".into(), "file:///tmp/two.json".into()];
        let picker = Picker::start_with_address(None, Some(address.clone()));
        assert!(answer(&picker).is_err());
        drop(picker);
        until(|| closed.load(Ordering::SeqCst) >= 5);
        plan.lock().unwrap().hold = true;
        let count = opened.load(Ordering::SeqCst);
        let picker = Picker::start_with_address(None, Some(address));
        until(|| opened.load(Ordering::SeqCst) > count);
        drop(picker);
        until(|| closed.load(Ordering::SeqCst) >= 6);
        drop(server);
        drop(bus);
    }
}
