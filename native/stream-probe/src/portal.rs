//! Standard permission-mediated single-monitor capture. Never reads the Python
//! restore token, writes user configuration, or grants compositor privileges.
use anyhow::{ensure, Context, Result};
use std::{
    collections::HashMap,
    os::fd::OwnedFd,
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
    pub serial: Option<String>,
    pub size: Option<(i32, i32)>,
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
    }
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
        };
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
        eprintln!("Choose the single monitor to test in KDE's screen-sharing dialog. This probe does not drive the LEDs.");
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
        session.node = streams[0].0;
        if let Some(value) = streams[0].1.get("id") {
            session.node = value.try_clone()?.try_into()?;
        }
        if let Some(value) = streams[0].1.get("pipewire-serial") {
            session.serial = Some(value.try_clone()?.try_into()?);
        }
        if let Some(value) = streams[0].1.get("size") {
            session.size = Some(value.try_clone()?.try_into()?);
        }
        let fd = session.remote()?;
        drop(portal);
        let _ = finish.send(());
        Ok((session, fd))
    }
}
