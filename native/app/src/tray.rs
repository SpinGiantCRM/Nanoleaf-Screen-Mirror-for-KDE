use crate::service::Control;
use ksni::blocking::TrayMethods;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::Sender,
        Arc,
    },
};
pub struct Tray {
    pub message: String,
    path: PathBuf,
    tx: Sender<Control>,
    settings_open: Arc<AtomicBool>,
}
impl Tray {
    fn settings(&mut self) {
        if self.settings_open.swap(true, Ordering::AcqRel) {
            return;
        }
        let child = std::env::current_exe().ok().and_then(|exe| {
            std::process::Command::new(exe)
                .arg("--settings")
                .arg(&self.path)
                .spawn()
                .ok()
        });
        if let Some(mut child) = child {
            let open = self.settings_open.clone();
            std::thread::spawn(move || {
                let _ = child.wait();
                open.store(false, Ordering::Release);
            });
        } else {
            self.settings_open.store(false, Ordering::Release);
        }
    }
}
impl ksni::Tray for Tray {
    fn activate(&mut self, _x: i32, _y: i32) {
        self.settings();
    }
    fn id(&self) -> String {
        "org.spingiantcrm.NanoleafNative".into()
    }
    fn title(&self) -> String {
        format!("Nanoleaf · {}", self.message)
    }
    fn icon_name(&self) -> String {
        std::env::current_exe()
            .ok()
            .and_then(|exe| crate::package::desktop_icon(&exe).ok())
            .unwrap_or_else(|| "preferences-desktop-color".into())
    }
    fn menu(&self) -> Vec<ksni::MenuItem<Self>> {
        use ksni::menu::StandardItem;
        vec![
            StandardItem {
                label: self.message.clone(),
                enabled: false,
                ..Default::default()
            }
            .into(),
            StandardItem {
                label: "Start mirroring".into(),
                activate: Box::new(|t: &mut Self| {
                    let _ = t.tx.send(Control::Start);
                }),
                ..Default::default()
            }
            .into(),
            StandardItem {
                label: "Stop mirroring".into(),
                activate: Box::new(|t: &mut Self| {
                    let _ = t.tx.send(Control::Stop);
                }),
                ..Default::default()
            }
            .into(),
            StandardItem {
                label: "Settings and calibration".into(),
                activate: Box::new(|t: &mut Self| {
                    t.settings();
                }),
                ..Default::default()
            }
            .into(),
            ksni::MenuItem::Separator,
            StandardItem {
                label: "Quit".into(),
                activate: Box::new(|t: &mut Self| {
                    let _ = t.tx.send(Control::Quit);
                }),
                ..Default::default()
            }
            .into(),
        ]
    }
}
pub fn spawn(
    path: PathBuf,
    tx: Sender<Control>,
    open_setup: bool,
) -> Result<ksni::blocking::Handle<Tray>, ksni::Error> {
    let mut tray = Tray {
        message: "Stopped".into(),
        path,
        tx,
        settings_open: Arc::new(AtomicBool::new(false)),
    };
    // A StatusNotifierWatcher may not be available yet at sign-in. Launch setup
    // directly rather than waiting for a tray update callback to be serviced.
    // The service's control listener is already ready before this function runs.
    if cfg!(feature = "gui") && open_setup {
        tray.settings();
    }
    tray.spawn()
}
