use crate::config::Store;
use eframe::egui;
use std::path::Path;

pub fn open(path: &Path) -> anyhow::Result<()> {
    let store = Store::load(path)?;
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([650.0, 620.0])
            .with_app_id("org.spingiantcrm.NanoleafNative"),
        ..Default::default()
    };
    eframe::run_native(
        "Nanoleaf Screen Mirror",
        options,
        Box::new(move |_| {
            Ok(Box::new(Settings {
                brightness: store.config.brightness,
                fps: store.config.fps,
                monitor: store.config.capture_monitor.clone(),
                store,
                message: String::new(),
                advanced: false,
            }))
        }),
    )
    .map_err(|e| anyhow::anyhow!(e.to_string()))
}

struct Settings {
    store: Store,
    brightness: f32,
    fps: u32,
    monitor: String,
    message: String,
    advanced: bool,
}
impl eframe::App for Settings {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::Frame::central_panel(ui.style())
            .inner_margin(18.0)
            .show(ui, |ui| self.content(ui));
    }
}
impl Settings {
    fn content(&mut self, ui: &mut egui::Ui) {
        ui.heading("Nanoleaf Screen Mirror");
        ui.label("One screen · one strip");
        ui.add_space(12.0);
        ui.label("Screen");
        ui.text_edit_singleline(&mut self.monitor);
        ui.small("Leave blank to follow the active screen.");
        ui.add(egui::Slider::new(&mut self.brightness, 0.0..=1.0).text("Brightness"));
        ui.add(egui::Slider::new(&mut self.fps, 1..=240).text("Target FPS"));
        ui.label(format!(
            "Strip zones: {}",
            self.store.config.device_zone_count
        ));
        ui.label(format!("Colour profile: {}", self.store.config.color_style));
        if ui.button("Save / Apply").clicked() {
            let mut doc = self.store.document.clone();
            doc["brightness"] = toml_edit::value(self.brightness as f64);
            doc["fps"] = toml_edit::value(self.fps as i64);
            doc["capture_monitor"] = toml_edit::value(self.monitor.clone());
            self.message = match self.store.save_document(doc) {
                Ok(()) => "Settings saved. A backup is retained.".into(),
                Err(e) => e.to_string(),
            };
        }
        if ui.button("Reload").clicked() {
            match Store::load(&self.store.path) {
                Ok(store) => {
                    self.brightness = store.config.brightness;
                    self.fps = store.config.fps;
                    self.monitor = store.config.capture_monitor.clone();
                    self.store = store;
                    self.message = "Settings reloaded.".into();
                }
                Err(e) => self.message = e.to_string(),
            }
        }
        ui.separator();
        ui.checkbox(&mut self.advanced, "Advanced / Troubleshooting");
        if self.advanced {
            ui.label(format!(
                "Calibration anchors: {:?}",
                self.store.config.anchors()
            ));
            ui.label(format!(
                "Channel order: {}",
                self.store.config.output_channel_order
            ));
            ui.label(format!(
                "SDR gains: {:.3} / {:.3} / {:.3}",
                self.store.config.led_calibration_profile_sdr.red_gain,
                self.store.config.led_calibration_profile_sdr.green_gain,
                self.store.config.led_calibration_profile_sdr.blue_gain
            ));
        }
        if !self.message.is_empty() {
            ui.separator();
            ui.label(&self.message);
        }
    }
}
