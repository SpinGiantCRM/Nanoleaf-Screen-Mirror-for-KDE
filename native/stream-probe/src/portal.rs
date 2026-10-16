//! Standard permission-mediated single-monitor capture. Never reads the Python
//! restore token, writes user configuration, or grants compositor privileges.
use anyhow::{ensure, Context, Result};
use std::{
    collections::HashMap,
    os::fd::OwnedFd,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use zbus::{
    blocking::{Connection, Proxy},
    zvariant::{OwnedObjectPath, OwnedValue, Value},
};
const DEST: &str = "org.freedesktop.portal.Desktop";
const PATH: &str = "/org/freedesktop/portal/desktop";
const IFACE: &str = "org.freedesktop.portal.ScreenCast";
pub struct Session {
    connection: Connection,
    path: OwnedObjectPath,
    pub node: u32,
    pub serial: Option<u64>,
    pub size: Option<(i32, i32)>,
    pub position: Option<(i32, i32)>,
    closed: Arc<AtomicBool>,
}
impl Drop for Session {
    fn drop(&mut self) {
        if let Ok(proxy) = Proxy::new(
            &self.connection,
            DEST,
            self.path.as_str(),
            "org.freedesktop.portal.Session",
        ) {
            let _: zbus::Result<()> = proxy.call("Close", &());
        }
        let _ = self.connection.clone().close();
    }
}
fn watch_closed(connection: &Connection, path: &OwnedObjectPath) -> Result<Arc<AtomicBool>> {
    let watcher = Proxy::new_owned(
        connection.clone(),
        DEST,
        path.clone(),
        "org.freedesktop.portal.Session",
    )?;
    let mut closures = watcher.receive_signal("Closed")?;
    let closed = Arc::new(AtomicBool::new(false));
    let flag = closed.clone();
    std::thread::spawn(move || {
        // EOF also means capture permission can no longer be established.
        let _ = closures.next();
        flag.store(true, Ordering::Release);
    });
    Ok(closed)
}
fn token() -> Result<String> {
    Ok(format!(
        "nanoleaf_{}_{}",
        std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
    ))
}
fn request<F>(
    connection: &Connection,
    portal: &Proxy<'_>,
    method: &str,
    call: F,
) -> Result<HashMap<String, OwnedValue>>
where
    F: FnOnce(&str) -> Result<OwnedObjectPath>,
{
    let sender = connection
        .unique_name()
        .context("No D-Bus unique name")?
        .as_str()
        .trim_start_matches(':')
        .replace('.', "_");
    let token = token()?;
    let path = format!("/org/freedesktop/portal/desktop/request/{sender}/{token}");
    let request = Proxy::new(
        connection,
        DEST,
        path.as_str(),
        "org.freedesktop.portal.Request",
    )?;
    let mut replies = request.receive_signal("Response")?;
    let handle = call(&token)?;
    ensure!(
        handle.as_str() == path,
        "Unexpected portal {method} response path"
    );
    let reply = replies
        .next()
        .context("Portal disconnected before answering")?;
    let (code, values): (u32, HashMap<String, OwnedValue>) = reply.body().deserialize()?;
    ensure!(
        code == 0,
        "Screen capture {method} cancelled or denied (response {code})"
    );
    let _ = portal; // Proxy keeps portal binding alive during the request.
    Ok(values)
}
impl Session {
    pub fn closed(&self) -> bool {
        self.closed.load(Ordering::Acquire)
    }
    pub fn remote(&self) -> Result<OwnedFd> {
        let portal = Proxy::new(&self.connection, DEST, PATH, IFACE)?;
        let fd: zbus::zvariant::OwnedFd = portal.call(
            "OpenPipeWireRemote",
            &(&self.path, HashMap::<&str, Value<'_>>::new()),
        )?;
        Ok(fd.into())
    }
    pub fn open() -> Result<(Self, OwnedFd)> {
        let connection = zbus::blocking::connection::Builder::session()?
            .method_timeout(Duration::from_secs(5))
            .build()?;
        // Signal iteration has no blocking timeout. A watchdog closes this own
        // connection after two minutes; it cannot affect another application's session.
        let (finish, timeout) = std::sync::mpsc::channel::<()>();
        let watchdog = connection.clone();
        std::thread::spawn(move || {
            if matches!(
                timeout.recv_timeout(Duration::from_secs(120)),
                Err(std::sync::mpsc::RecvTimeoutError::Timeout)
            ) {
                let _ = watchdog.close();
            }
        });
        let portal = Proxy::new(&connection, DEST, PATH, IFACE)?;
        let session_token = token()?;
        let created = request(&connection, &portal, "CreateSession", |handle| {
            Ok(portal.call(
                "CreateSession",
                &(HashMap::from([
                    ("handle_token", Value::from(handle)),
                    ("session_handle_token", Value::from(session_token.as_str())),
                ]),),
            )?)
        })?;
        // The specification intentionally encodes session_handle as a string.
        let path: String = created
            .get("session_handle")
            .context("No session handle")?
            .try_clone()?
            .try_into()?;
        let path: OwnedObjectPath = path.try_into()?;
        let mut session = Self {
            connection: connection.clone(),
            path,
            node: 0,
            serial: None,
            size: None,
            position: None,
            closed: Arc::new(AtomicBool::new(false)),
        };
        // Subscribe before Start, including a closure emitted before its reply.
        session.closed = watch_closed(&connection, &session.path)?;
        let permission = crate::permission::Permission::user()?;
        let restore = permission.load()?;
        // A submitted token is single-use. Remove only our own token before
        // submission; a successful Start returns its replacement.
        if restore.is_some() {
            permission.invalidate()?;
        }
        request(&connection, &portal, "SelectSources", |handle| {
            let mut options = HashMap::from([
                ("handle_token", Value::from(handle)),
                ("types", Value::from(1_u32)),
                ("multiple", Value::from(false)),
                ("cursor_mode", Value::from(1_u32)),
                ("persist_mode", Value::from(2_u32)),
            ]);
            if let Some(token) = &restore {
                options.insert("restore_token", Value::from(token.as_str()));
            }
            Ok(portal.call("SelectSources", &(&session.path, options))?)
        })?;
        eprintln!("Select the configured monitor if KDE asks for screen-sharing permission.");
        let started = request(&connection, &portal, "Start", |handle| {
            Ok(portal.call(
                "Start",
                &(
                    &session.path,
                    "",
                    HashMap::from([("handle_token", Value::from(handle))]),
                ),
            )?)
        })?;
        if let Some(value) = started.get("restore_token") {
            let token: String = value.try_clone()?.try_into()?;
            permission.save(&token)?;
        }
        let streams: Vec<(u32, HashMap<String, OwnedValue>)> = started
            .get("streams")
            .context("No screen stream")?
            .try_clone()?
            .try_into()?;
        ensure!(streams.len() == 1, "Select exactly one monitor");
        let target = stream_target(streams[0].0, &streams[0].1)?;
        session.node = target.node;
        session.serial = target.serial;
        if let Some(value) = streams[0].1.get("size") {
            session.size = Some(value.try_clone()?.try_into()?);
        }
        if let Some(value) = streams[0].1.get("position") {
            session.position = Some(value.try_clone()?.try_into()?);
        }
        let fd = session.remote()?;
        drop(portal);
        let _ = finish.send(());
        Ok((session, fd))
    }
}

struct StreamTarget {
    node: u32,
    serial: Option<u64>,
}
fn stream_target(node: u32, properties: &HashMap<String, OwnedValue>) -> Result<StreamTarget> {
    // `id` is an opaque source identity, never a PipeWire node ID. Version 6
    // specifies a uint64 serial; accept older KDE's decimal-string serial too.
    let serial = properties
        .get("pipewire-serial")
        .map(|value| -> Result<u64> {
            let serial = if let Ok(serial) = u64::try_from(value) {
                serial
            } else {
                <&str>::try_from(value)
                    .context("Invalid PipeWire serial type")?
                    .parse::<u64>()
                    .context("Invalid PipeWire serial")?
            };
            ensure!(serial > 0, "Invalid zero PipeWire serial");
            Ok(serial)
        })
        .transpose()?;
    Ok(StreamTarget { node, serial })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader},
        process::{Child, Command, Stdio},
        time::Instant,
    };
    struct Bus(Child);
    impl Drop for Bus {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    #[test]
    fn stream_identity_never_replaces_node_and_uint64_serial_is_preserved() {
        let properties = HashMap::from([
            (
                "id".into(),
                OwnedValue::try_from(Value::from("DP-1-source")).unwrap(),
            ),
            ("pipewire-serial".into(), OwnedValue::from(u64::MAX)),
        ]);
        let target = stream_target(42, &properties).unwrap();
        assert_eq!(target.node, 42);
        assert_eq!(target.serial, Some(u64::MAX));
        let target = stream_target(42, &HashMap::new()).unwrap();
        assert_eq!(target.node, 42);
        assert_eq!(target.serial, None);
        // Older KDE responses used a string serial and a numeric id. The id is
        // still opaque metadata; it must not change the tuple's PipeWire node.
        let properties = HashMap::from([
            ("id".into(), OwnedValue::from(999_u32)),
            (
                "pipewire-serial".into(),
                OwnedValue::try_from(Value::from("123456")).unwrap(),
            ),
        ]);
        let target = stream_target(42, &properties).unwrap();
        assert_eq!(target.node, 42);
        assert_eq!(target.serial, Some(123456));
    }

    #[test]
    fn malformed_present_serial_never_silently_falls_back_to_a_reused_node() {
        for value in [
            OwnedValue::from(0_u64),
            OwnedValue::from(-1_i64),
            OwnedValue::try_from(Value::from("not-a-serial")).unwrap(),
            OwnedValue::try_from(Value::from("18446744073709551616")).unwrap(),
        ] {
            assert!(
                stream_target(42, &HashMap::from([("pipewire-serial".into(), value)])).is_err()
            );
        }
    }
    #[test]
    fn permission_closure_and_bus_loss_are_observed_without_pipewire() {
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
        let server = zbus::blocking::connection::Builder::address(address.trim())
            .unwrap()
            .name(DEST)
            .unwrap()
            .build()
            .unwrap();
        let client = zbus::blocking::connection::Builder::address(address.trim())
            .unwrap()
            .build()
            .unwrap();
        let path: OwnedObjectPath = "/org/freedesktop/portal/desktop/session/test/one"
            .try_into()
            .unwrap();
        let closed = watch_closed(&client, &path).unwrap();
        assert!(!closed.load(Ordering::Acquire));
        server
            .emit_signal(
                None::<&str>,
                path.clone(),
                "org.freedesktop.portal.Session",
                "Closed",
                &(HashMap::<String, OwnedValue>::new(),),
            )
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(3);
        while !closed.load(Ordering::Acquire) {
            assert!(Instant::now() < deadline, "Closed signal was missed");
            std::thread::sleep(Duration::from_millis(5));
        }
        let disconnected = watch_closed(&client, &path).unwrap();
        let _ = client.clone().close();
        let deadline = Instant::now() + Duration::from_secs(3);
        while !disconnected.load(Ordering::Acquire) {
            assert!(Instant::now() < deadline, "Connection loss was missed");
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}
