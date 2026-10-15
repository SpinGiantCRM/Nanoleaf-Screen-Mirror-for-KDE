//! On-demand native settings and calibration; closing it leaves the tray service alive.
use crate::{
    config::{Config, LedProfile, Store},
    service::{self, Control, Status},
};
use eframe::egui;
use std::{
    path::Path,
    time::{Duration, Instant},
};
pub fn open(path: &Path) -> anyhow::Result<()> {
    let store = Store::load(path)?;
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([740.0, 780.0])
            .with_app_id("org.spingiantcrm.NanoleafNative"),
        ..Default::default()
    };
    eframe::run_native(
        "Nanoleaf Screen Mirror",
        options,
        Box::new(move |_| {
            Ok(Box::new(Settings {
                draft: store.config.clone(),
                store,
                message: String::new(),
                advanced: false,
                setup: false,
                status: None,
                last_poll: Instant::now() - Duration::from_secs(2),
                preview_zone: 0,
                screens: crate::screens::names().unwrap_or_default(),
                hdr_profile: false,
                picker: None,
                profile_action: None,
            }))
        }),
    )
    .map_err(|e| anyhow::anyhow!(e.to_string()))
}
struct Settings {
    store: Store,
    draft: Config,
    message: String,
    advanced: bool,
    setup: bool,
    status: Option<Status>,
    last_poll: Instant,
    preview_zone: usize,
    screens: Vec<String>,
    hdr_profile: bool,
    picker: Option<crate::portal_file::Picker>,
    profile_action: Option<ProfileAction>,
}
enum ProfileAction {
    Import,
    Export(String, LedProfile),
}
impl eframe::App for Settings {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        if let Some(result) = self.picker.as_ref().and_then(|p| p.result()) {
            self.picker = None;
            self.message = match (result, self.profile_action.take()) {
                (Ok(Some(path)), Some(ProfileAction::Import)) => {
                    match crate::profile::load(&path) {
                        Ok((preset, profile)) => {
                            self.hdr_profile = preset == "hdr";
                            if self.hdr_profile {
                                self.draft.led_calibration_profile_hdr = profile;
                            } else {
                                self.draft.led_calibration_profile_sdr = profile;
                            }
                            "Profile imported into the draft. Save / Apply to use it.".into()
                        }
                        Err(e) => format!("Profile not imported: {e}"),
                    }
                }
                (Ok(Some(path)), Some(ProfileAction::Export(preset, profile))) => {
                    match crate::profile::export(&path, &preset, &profile) {
                        Ok(Some(_)) => "Profile exported. The previous file was backed up.".into(),
                        Ok(None) => "Profile exported.".into(),
                        Err(e) => format!("Profile not exported: {e}"),
                    }
                }
                (Ok(None), _) => "File selection cancelled".into(),
                (Err(e), _) => format!("File selection unavailable: {e}"),
                _ => "File selection cancelled".into(),
            };
        }
        if self.last_poll.elapsed() > Duration::from_secs(1) {
            self.status = service::send(&Control::Status).ok();
            self.last_poll = Instant::now();
        }
        ui.ctx().request_repaint_after(Duration::from_secs(1));
        egui::Frame::central_panel(ui.style())
            .inner_margin(18.0)
            .show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.content(ui));
            });
    }
}
fn choice(ui: &mut egui::Ui, label: &str, value: &mut String, options: &[&str]) {
    egui::ComboBox::from_label(label)
        .selected_text(value.as_str())
        .show_ui(ui, |ui| {
            for &option in options {
                ui.selectable_value(value, option.to_string(), option);
            }
        });
}
fn profile_ui(ui: &mut egui::Ui, p: &mut LedProfile) {
    ui.small("Use your measured profile. These adjustments affect emitted colour.");
    for (name, saved, minimum, maximum) in [
        ("Red gain", p.red_gain, 0.5, 1.5),
        ("Green gain", p.green_gain, 0.5, 1.5),
        ("Blue gain", p.blue_gain, 0.5, 1.5),
        ("LED gamma", p.led_gamma, 1.0, 4.0),
        ("White balance", p.white_balance_temperature, -1.0, 1.0),
        ("Neutral luminance", p.neutral_luminance_gain, 0.7, 1.5),
        ("Chroma compression", p.chroma_compression, 0.0, 0.6),
        ("Black cutoff", p.black_luminance_cutoff, 0.0, 0.03),
        ("Black knee", p.black_luminance_knee, 0.0005, 0.03),
    ] {
        let effective = saved.clamp(minimum, maximum);
        if saved != effective {
            ui.small(format!(
                "{name}: saved {saved}, used as {effective}. Your saved value is preserved."
            ));
        }
    }
    ui.add(
        egui::Slider::new(&mut p.red_gain, 0.5..=1.5)
            .clamping(egui::SliderClamping::Edits)
            .text("Red gain"),
    );
    ui.add(
        egui::Slider::new(&mut p.green_gain, 0.5..=1.5)
            .clamping(egui::SliderClamping::Edits)
            .text("Green gain"),
    );
    ui.add(
        egui::Slider::new(&mut p.blue_gain, 0.5..=1.5)
            .clamping(egui::SliderClamping::Edits)
            .text("Blue gain"),
    );
    ui.add(
        egui::Slider::new(&mut p.led_gamma, 1.0..=4.0)
            .clamping(egui::SliderClamping::Edits)
            .text("LED gamma"),
    );
    ui.add(
        egui::Slider::new(&mut p.white_balance_temperature, -1.0..=1.0)
            .clamping(egui::SliderClamping::Edits)
            .text("White balance"),
    );
    ui.add(
        egui::Slider::new(&mut p.neutral_luminance_gain, 0.7..=1.5)
            .clamping(egui::SliderClamping::Edits)
            .text("Neutral luminance"),
    );
    ui.add(
        egui::Slider::new(&mut p.chroma_compression, 0.0..=0.6)
            .clamping(egui::SliderClamping::Edits)
            .text("Chroma compression"),
    );
    ui.add(
        egui::Slider::new(&mut p.black_luminance_cutoff, 0.0..=0.03)
            .clamping(egui::SliderClamping::Edits)
            .text("Black cutoff"),
    );
    ui.add(
        egui::Slider::new(&mut p.black_luminance_knee, 0.0005..=0.03)
            .clamping(egui::SliderClamping::Edits)
            .text("Black knee"),
    );
    if p.color_matrix.len() == 9 {
        ui.label("Measured colour matrix");
        egui::Grid::new("profile-matrix").show(ui, |ui| {
            for row in p.color_matrix.as_chunks_mut::<3>().0 {
                for v in row {
                    ui.add(egui::DragValue::new(v).speed(0.001));
                }
                ui.end_row();
            }
        });
    }
}
fn save_profile(doc: &mut toml_edit::DocumentMut, key: &str, p: &LedProfile) {
    for (field, value) in [
        ("red_gain", p.red_gain),
        ("green_gain", p.green_gain),
        ("blue_gain", p.blue_gain),
        ("led_gamma", p.led_gamma),
        ("white_balance_temperature", p.white_balance_temperature),
        ("chroma_compression", p.chroma_compression),
        ("neutral_luminance_gain", p.neutral_luminance_gain),
        ("black_luminance_cutoff", p.black_luminance_cutoff),
        ("black_luminance_knee", p.black_luminance_knee),
        ("dark_sample_stabilize_on", p.dark_sample_stabilize_on),
        ("dark_sample_stabilize_off", p.dark_sample_stabilize_off),
    ] {
        doc[key][field] = toml_edit::value(value);
    }
    let mut matrix = toml_edit::Array::new();
    for v in &p.color_matrix {
        matrix.push(*v);
    }
    doc[key]["color_matrix"] = toml_edit::value(matrix);
}
impl Settings {
    fn control(&mut self, command: Control) {
        self.message = match service::send(&command) {
            Ok(s) => {
                self.status = Some(s);
                "Request sent".into()
            }
            Err(e) => e.to_string(),
        };
        self.last_poll = Instant::now() - Duration::from_secs(2);
    }
    fn content(&mut self, ui: &mut egui::Ui) {
        ui.heading("Nanoleaf Screen Mirror");
        ui.label("One screen · one strip");
        ui.add_space(8.0);
        if let Some(s) = &self.status {
            ui.label(&s.message);
            ui.small(format!(
                "{} · {:.1} acknowledged packets/s",
                s.model, s.effective_fps
            ));
            if !s.preview {
                ui.small("Capture: SDR sRGB, including on HDR desktops · active calibration: SDR");
            }
        } else {
            ui.label("The native tray service is not running.");
        }
        ui.horizontal(|ui| {
            if ui.button("Start mirroring").clicked() {
                self.control(Control::Start);
            }
            if ui.button("Stop mirroring").clicked() {
                self.control(Control::Stop);
            }
        });
        ui.separator();
        ui.label("Screen");
        egui::ComboBox::from_id_salt("selected-monitor")
            .selected_text(if self.draft.capture_monitor.is_empty() {
                "Active screen"
            } else {
                &self.draft.capture_monitor
            })
            .show_ui(ui, |ui| {
                ui.selectable_value(
                    &mut self.draft.capture_monitor,
                    String::new(),
                    "Active screen",
                );
                for name in &self.screens {
                    ui.selectable_value(&mut self.draft.capture_monitor, name.clone(), name);
                }
            });
        if !self.draft.capture_monitor.is_empty()
            && !self.screens.contains(&self.draft.capture_monitor)
        {
            ui.small(
                "The saved screen is unavailable. It will be retried without switching screens.",
            );
        }
        ui.add(egui::Slider::new(&mut self.draft.brightness, 0.0..=1.0).text("Brightness"));
        ui.add(egui::Slider::new(&mut self.draft.fps, 1..=240).text("Target FPS"));
        choice(
            ui,
            "Colour style",
            &mut self.draft.color_style,
            &["reference", "natural", "ambient", "vivid", "punchy"],
        );
        ui.add(egui::Slider::new(&mut self.draft.smoothing, 0.0..=1.0).text("Response speed"));
        ui.add(
            egui::Slider::new(&mut self.draft.smoothing_speed, 0.0..=4.0).text("Motion response"),
        );
        if ui.button("Use fast response").clicked() {
            self.draft.enable_fast_response();
            self.message = "Fast response selected. Save / Apply to use it.".into();
        }
        ui.small(
            "Fast response follows changes promptly; small colour variations may be more visible.",
        );
        if self.draft.zone_temporal_accumulation {
            ui.small("Additional temporal averaging is enabled and can delay colour changes.");
        }
        ui.checkbox(
            &mut self.draft.letterbox_detection,
            "Follow content inside black bars",
        );
        ui.checkbox(
            &mut self.draft.start_on_launch,
            "Start mirroring when the tray launches",
        );
        ui.checkbox(&mut self.setup, "Strip setup and calibration");
        if self.setup {
            ui.group(|ui|{
            egui::ComboBox::from_label("Strip model")
                .selected_text(if self.draft.device_pid == 0x8201 { "NL82K1" } else { "NL82K2" })
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.draft.device_pid, 0x8201, "NL82K1");
                    ui.selectable_value(&mut self.draft.device_pid, 0x8202, "NL82K2");
                });
            ui.label("Manual zone count");ui.add(egui::DragValue::new(&mut self.draft.device_zone_count).range(0..=512));
            self.preview_zone=self.preview_zone.min(self.draft.device_zone_count.saturating_sub(1));
            ui.horizontal(|ui|{ui.label("Preview zone");ui.add(egui::DragValue::new(&mut self.preview_zone).range(0..=self.draft.device_zone_count.saturating_sub(1)));if ui.button("Locate zone").clicked(){self.control(Control::Preview{rgb:[80;3],zone:Some(self.preview_zone)});}});
            ui.small("Preview pauses mirroring and clears after ten seconds. Save the count before testing it.");
            egui::Grid::new("anchors").show(ui,|ui|{for (name,value) in [("Top left",&mut self.draft.calibration.corner_anchor_top_left),("Top right",&mut self.draft.calibration.corner_anchor_top_right),("Bottom right",&mut self.draft.calibration.corner_anchor_bottom_right),("Bottom left",&mut self.draft.calibration.corner_anchor_bottom_left)]{ui.label(name);ui.add(egui::DragValue::new(value).range(-1..=self.draft.device_zone_count.saturating_sub(1)as i64));ui.end_row();}});
            choice(ui,"Strip channel order",&mut self.draft.output_channel_order,&["grb","rgb","rbg","gbr","brg","bgr"]);ui.checkbox(&mut self.draft.reverse_zones,"Reverse strip order");
            ui.horizontal(|ui|{for (label,rgb) in [("Red",[80,0,0]),("Green",[0,80,0]),("Blue",[0,0,80]),("Grey",[64;3]),("Black",[0;3])]{if ui.button(label).clicked(){self.control(Control::Preview{rgb,zone:None});}}});
        });
        }
        ui.horizontal(|ui| {
            if ui.button("Save / Apply").clicked() {
                self.save();
            }
            if ui.button("Reload").clicked() {
                match Store::load(&self.store.path) {
                    Ok(s) => {
                        self.draft = s.config.clone();
                        self.store = s;
                        self.message = "Settings reloaded".into();
                    }
                    Err(e) => self.message = e.to_string(),
                }
            }
        });
        ui.separator();
        ui.checkbox(&mut self.advanced, "Advanced / Troubleshooting");
        if self.advanced {
            ui.horizontal(|ui| {
                if ui.button("Launch native tray at login").clicked() {
                    self.message = crate::package::autostart(true)
                        .map(|_| {
                            "Native tray login launch enabled. Python startup is unchanged.".into()
                        })
                        .unwrap_or_else(|e| e.to_string());
                }
                if ui.button("Disable native login launch").clicked() {
                    self.message = crate::package::autostart(false)
                        .map(|_| "Native login launch disabled.".into())
                        .unwrap_or_else(|e| e.to_string());
                }
            });
            if self.picker.is_some() {
                ui.label("Choose the profile file in KDE's file dialog.");
                if ui.button("Cancel file selection").clicked() {
                    self.picker = None;
                    self.profile_action = None;
                    self.message = "File selection cancelled".into();
                }
            } else {
                ui.horizontal(|ui| {
                    if ui.button("Import measured profile…").clicked() {
                        self.picker = Some(crate::portal_file::Picker::start(None));
                        self.profile_action = Some(ProfileAction::Import);
                    }
                    if ui.button("Export current profile…").clicked() {
                        let (preset, profile) = if self.hdr_profile {
                            ("hdr", self.draft.led_calibration_profile_hdr.clone())
                        } else {
                            ("sdr", self.draft.led_calibration_profile_sdr.clone())
                        };
                        self.picker = Some(crate::portal_file::Picker::start(Some(format!(
                            "nanoleaf-led-{preset}.json"
                        ))));
                        self.profile_action = Some(ProfileAction::Export(preset.into(), profile));
                    }
                });
            }
            choice(
                ui,
                "Capture",
                &mut self.draft.capture_backend,
                &["auto", "kwin-dbus", "xdg-portal"],
            );
            ui.small("Streaming uses the portal permission and a separate capture worker. KWin capture remains the fallback.");
            choice(
                ui,
                "Performance priority",
                &mut self.draft.performance_priority,
                &["normal", "high", "very_high"],
            );
            if let Some(error) = self.status.as_ref().and_then(|s| s.priority.error.as_ref()) {
                ui.small(format!(
                    "Priority adjustment unavailable: {error}. Mirroring continues."
                ));
            }
            ui.group(|ui|{
            choice(ui,"Sync mode",&mut self.draft.sync_mode,&["standard","4d"]);
            ui.small("4D adds at most one inferred packet per frame, within one colour code. Reference/accuracy and dithering disable it. It never raises capture FPS.");
            choice(ui,"Sampling",&mut self.draft.sampling_mode,&["auto","palette_adaptive","edge_direct","area_average","peak_luma","vivid_weighted","wavelet"]);choice(ui,"Sampling quality",&mut self.draft.sampling_quality,&["high","balanced","low"]);choice(ui,"Motion preset",&mut self.draft.motion_preset,&["responsive","calm","dynamic"]);choice(ui,"Light spread",&mut self.draft.light_spread,&["off","precise","balanced","soft"]);
            ui.checkbox(&mut self.draft.accuracy_mode,"Accuracy mode");
            ui.checkbox(&mut self.draft.multi_moment_zone_colors,"Dominant colour from actual zone pixels");
            ui.checkbox(&mut self.draft.scene_adaptive_profiles,"Respond faster to changing scenes");
            ui.small("Reference/accuracy bypass appearance policies. Legacy virtual oversampling requests full pixel coverage; physical zone count and privacy masks remain authoritative.");ui.checkbox(&mut self.draft.blue_noise_dither,"Sub-code temporal dithering");ui.checkbox(&mut self.draft.zone_temporal_accumulation,"Temporal sample accumulation");
            ui.checkbox(&mut self.draft.zone_box_filter_sampling,"Full-area box sampling");
            choice(ui,"Edge depth",&mut self.draft.edge_locality,&["tight","balanced","wide"]);
            ui.add(egui::Slider::new(&mut self.draft.layout_inset,0.0..=0.4).clamping(egui::SliderClamping::Edits).text("Layout inset"));
            ui.add(egui::Slider::new(&mut self.draft.layout_scale,0.5..=1.0).clamping(egui::SliderClamping::Edits).text("Layout scale"));
            ui.separator();ui.checkbox(&mut self.hdr_profile,"Edit HDR profile");if self.hdr_profile{profile_ui(ui,&mut self.draft.led_calibration_profile_hdr);}else{profile_ui(ui,&mut self.draft.led_calibration_profile_sdr);}
            ui.small("KWin screenshots already contain SDR sRGB colour. The SDR LED profile applies to that capture even on an HDR desktop. Your HDR profile is retained.");
            if let Some(s)=&self.status{ui.separator();ui.label(format!("Capture {:.2} ms · colour {:.2} ms · USB {:.2} ms",s.capture_ms,s.processing_ms,s.usb_ms));ui.label(format!("Software response {:.2} ms · {} acknowledged packets · {} missed deadlines",s.response_ms,s.frames,s.missed_deadlines));ui.small("Response runs from capture request or stream sampling work to USB acknowledgement; emitted-light delay is not measured.");ui.small(match s.response_clock.as_str(){"capture-work"=>"Timing starts when the stream frame begins processing.","cached-work"=>"Timing starts when the unchanged image is reprocessed.","source-presentation"=>"Legacy timing starts at the display presentation marker.",_=>"Timing starts at capture or processing."});if let Some(age)=s.source_presentation_age_ms{ui.small(format!("Display presentation age {:.2} ms (separate from capture latency)",age));}ui.small(format!("{} inferred packets (included in acknowledged packets)",s.predicted_frames));ui.label(format!("Manual {} · reported {} · connections {}",s.manual_zones,s.reported_zones,s.reconnects));ui.label(&s.backend);}
            if let Some(t)=self.status.as_ref().and_then(|s|s.usb_transaction.as_ref()) {
                ui.small(format!("Last USB packet: drain {:.3} ms · write {:.3} ms · wait for acknowledgement {:.3} ms",t.drain_ms,t.write_ms,t.ack_wait_ms));
                ui.small(format!("First response after {:.3} ms · {} reports written / {} received",t.first_report_wait_ms,t.written_reports,t.response_reports));
            }
            if let Some(s)=&self.status {
                ui.small(format!("{} packets reprocessed from an unchanged shared image; these are not new captured frames.",s.reused_source_packets));
                if s.last_source_reused {ui.small("Last response timing starts at unchanged-image processing, not the original capture timestamp.");}
            }
        });
        }
        if !self.message.is_empty() {
            ui.separator();
            ui.label(&self.message);
        }
    }
    fn save(&mut self) {
        let mut doc = self.store.document.clone();
        for (key, val) in [
            ("brightness", self.draft.brightness),
            ("smoothing", self.draft.smoothing),
            ("smoothing_speed", self.draft.smoothing_speed),
            ("layout_inset", self.draft.layout_inset),
            ("layout_scale", self.draft.layout_scale),
        ] {
            doc[key] = toml_edit::value(val);
        }
        doc["schema_version"] = toml_edit::value(2_i64);
        doc["fps"] = toml_edit::value(self.draft.fps as i64);
        for (key, val) in [
            ("capture_monitor", &self.draft.capture_monitor),
            ("capture_backend", &self.draft.capture_backend),
            ("color_style", &self.draft.color_style),
            ("sampling_mode", &self.draft.sampling_mode),
            ("sampling_quality", &self.draft.sampling_quality),
            ("motion_preset", &self.draft.motion_preset),
            ("light_spread", &self.draft.light_spread),
            ("performance_priority", &self.draft.performance_priority),
            ("sync_mode", &self.draft.sync_mode),
            ("edge_locality", &self.draft.edge_locality),
            ("output_channel_order", &self.draft.output_channel_order),
        ] {
            doc[key] = toml_edit::value(val.clone());
        }
        for (key, val) in [
            ("letterbox_detection", self.draft.letterbox_detection),
            ("start_on_launch", self.draft.start_on_launch),
            ("accuracy_mode", self.draft.accuracy_mode),
            ("blue_noise_dither", self.draft.blue_noise_dither),
            (
                "zone_temporal_accumulation",
                self.draft.zone_temporal_accumulation,
            ),
            ("reverse_zones", self.draft.reverse_zones),
            (
                "multi_moment_zone_colors",
                self.draft.multi_moment_zone_colors,
            ),
            (
                "scene_adaptive_profiles",
                self.draft.scene_adaptive_profiles,
            ),
        ] {
            doc[key] = toml_edit::value(val);
        }
        doc["device_pid"] = toml_edit::value(self.draft.device_pid as i64);
        doc["device_zone_count"] = toml_edit::value(self.draft.device_zone_count as i64);
        doc["calibration"]["device_zone_count"] =
            toml_edit::value(self.draft.device_zone_count as i64);
        doc["calibration"]["output_channel_order"] =
            toml_edit::value(self.draft.output_channel_order.clone());
        doc["calibration"]["reverse_zones"] = toml_edit::value(self.draft.reverse_zones);
        for (key, val) in [
            (
                "corner_anchor_top_left",
                self.draft.calibration.corner_anchor_top_left,
            ),
            (
                "corner_anchor_top_right",
                self.draft.calibration.corner_anchor_top_right,
            ),
            (
                "corner_anchor_bottom_right",
                self.draft.calibration.corner_anchor_bottom_right,
            ),
            (
                "corner_anchor_bottom_left",
                self.draft.calibration.corner_anchor_bottom_left,
            ),
        ] {
            doc["calibration"][key] = toml_edit::value(val);
        }
        save_profile(
            &mut doc,
            "led_calibration_profile_sdr",
            &self.draft.led_calibration_profile_sdr,
        );
        save_profile(
            &mut doc,
            "led_calibration_profile_hdr",
            &self.draft.led_calibration_profile_hdr,
        );
        self.message = match self.store.save_document(doc) {
            Ok(()) => {
                let _ = service::send(&Control::Reload);
                "Settings saved. A backup is retained.".into()
            }
            Err(e) => e.to_string(),
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rendering_profile_controls_does_not_clamp_saved_calibration() {
        let mut profile = LedProfile {
            red_gain: 0.42,
            led_gamma: 0.7,
            black_luminance_knee: 0.0001,
            ..Default::default()
        };
        let original = serde_json::to_value(&profile).unwrap();
        let context = egui::Context::default();
        let mut output = context.run_ui(Default::default(), |ui| profile_ui(ui, &mut profile));
        output.textures_delta.clear();
        assert_eq!(serde_json::to_value(profile).unwrap(), original);
    }
    #[test]
    fn profile_round_trip_preserves_decimal_calibration_and_unknown_keys() {
        let original = "schema_version=2\ndevice_zone_count=48\n[led_calibration_profile_sdr]\nred_gain=0.873123456789\nblack_luminance_cutoff=0.0032\nblack_luminance_knee=0.0024\ndark_sample_stabilize_on=0.008\ndark_sample_stabilize_off=0.025\ncustom_measurement_note='keep this'\n";
        let store = Store::parse(Path::new("unused.toml"), original.as_bytes().to_vec()).unwrap();
        let mut doc = store.document.clone();
        save_profile(
            &mut doc,
            "led_calibration_profile_sdr",
            &store.config.led_calibration_profile_sdr,
        );
        let before: toml::Table = toml::from_str(original).unwrap();
        let after: toml::Table = toml::from_str(&doc.to_string()).unwrap();
        for (key, value) in before["led_calibration_profile_sdr"].as_table().unwrap() {
            assert_eq!(&after["led_calibration_profile_sdr"][key], value, "{key}");
        }
    }
}
