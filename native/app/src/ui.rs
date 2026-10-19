//! On-demand native settings and calibration; closing it leaves the tray service alive.
use crate::{
    config::{Config, LedProfile, Store},
    onboarding::{self, Step},
    service::{self, Control, Status},
};
use eframe::egui;
use std::{
    path::Path,
    time::{Duration, Instant},
};
pub fn open(path: &Path) -> anyhow::Result<()> {
    let store = Store::load(path)?;
    let icon = eframe::icon_data::from_png_bytes(include_bytes!(
        "../../../assets/icons/hicolor/128x128/apps/nanoleaf-kde-sync.png"
    ))?;
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([960.0, 800.0])
            .with_min_inner_size([760.0, 620.0])
            .with_icon(icon)
            .with_app_id("org.spingiantcrm.NanoleafNative"),
        ..Default::default()
    };
    eframe::run_native(
        "Nanoleaf Screen Mirror",
        options,
        Box::new(move |creation| {
            configure_style(&creation.egui_ctx);
            Ok(Box::new(Settings {
                draft: store.config.clone(),
                page: if onboarding::needs_setup(&store.config) {
                    Page::Strip
                } else {
                    Page::Mirror
                },
                store,
                message: String::new(),
                setup_step: Step::Connect,
                usb_check: None,
                preview_settings_ready: true,
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
    page: Page,
    setup_step: Step,
    usb_check: Option<String>,
    preview_settings_ready: bool,
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

#[derive(Clone, Copy, PartialEq, Eq)]
enum Page {
    Mirror,
    Strip,
    Colour,
    Advanced,
}

const ACCENT: egui::Color32 = egui::Color32::from_rgb(126, 226, 188);
const MUTED: egui::Color32 = egui::Color32::from_rgb(159, 177, 174);

fn configure_style(context: &egui::Context) {
    context.set_theme(egui::Theme::Dark);
    let mut style = (*context.style_of(egui::Theme::Dark)).clone();
    style.visuals = egui::Visuals::dark();
    style.visuals.panel_fill = egui::Color32::from_rgb(17, 23, 25);
    style.visuals.window_fill = egui::Color32::from_rgb(24, 32, 34);
    style.visuals.override_text_color = Some(egui::Color32::from_rgb(231, 239, 236));
    style.visuals.selection.bg_fill = egui::Color32::from_rgb(43, 83, 70);
    style.visuals.selection.stroke = egui::Stroke::new(1.0, ACCENT);
    style.visuals.widgets.inactive.weak_bg_fill = egui::Color32::from_rgb(36, 48, 50);
    style.visuals.widgets.hovered.weak_bg_fill = egui::Color32::from_rgb(48, 69, 64);
    style.spacing.item_spacing = egui::vec2(12.0, 12.0);
    style.spacing.button_padding = egui::vec2(14.0, 9.0);
    style.spacing.interact_size.y = 32.0;
    style.spacing.slider_width = 210.0;
    style.spacing.combo_width = 190.0;
    for (kind, size) in [
        (egui::TextStyle::Heading, 26.0),
        (egui::TextStyle::Body, 14.0),
        (egui::TextStyle::Button, 14.0),
        (egui::TextStyle::Small, 12.0),
    ] {
        style
            .text_styles
            .insert(kind, egui::FontId::proportional(size));
    }
    context.set_style_of(egui::Theme::Dark, style);
}

fn card(ui: &mut egui::Ui, title: &str, description: &str, body: impl FnOnce(&mut egui::Ui)) {
    egui::Frame::new()
        .fill(egui::Color32::from_rgb(25, 34, 36))
        .stroke(egui::Stroke::new(1.0, egui::Color32::from_rgb(43, 57, 57)))
        .corner_radius(12)
        .inner_margin(18.0)
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.label(egui::RichText::new(title).size(17.0).strong());
            if !description.is_empty() {
                ui.label(egui::RichText::new(description).color(MUTED));
            }
            ui.add_space(4.0);
            body(ui);
        });
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
            .inner_margin(24.0)
            .show(ui, |ui| self.layout(ui));
    }
}
fn choice(ui: &mut egui::Ui, label: &str, value: &mut String, options: &[&str]) {
    egui::ComboBox::from_label(label)
        .selected_text(option_label(value))
        .show_ui(ui, |ui| {
            for &option in options {
                ui.selectable_value(value, option.to_string(), option_label(option));
            }
        });
}

fn option_label(value: &str) -> &str {
    match value {
        "auto" => "Automatic",
        "kwin-dbus" => "KWin ScreenShot2",
        "xdg-portal" => "Portal / Vulkan",
        "reference" => "Reference",
        "natural" => "Natural",
        "ambient" => "Ambient",
        "vivid" => "Vivid",
        "punchy" => "Punchy",
        "normal" => "Normal",
        "high" => "High",
        "very_high" => "Very high",
        "standard" => "Standard",
        "4d" => "4D",
        "palette_adaptive" => "Adaptive palette",
        "edge_direct" => "Direct edge",
        "area_average" => "Area average",
        "peak_luma" => "Peak luminance",
        "vivid_weighted" => "Vivid weighted",
        "wavelet" => "Wavelet",
        "balanced" => "Balanced",
        "low" => "Low",
        "responsive" => "Responsive",
        "calm" => "Calm",
        "dynamic" => "Dynamic",
        "off" => "Off",
        "precise" => "Precise",
        "soft" => "Soft",
        "tight" => "Tight",
        "wide" => "Wide",
        _ => value,
    }
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
    fn layout(&mut self, ui: &mut egui::Ui) {
        egui::Panel::bottom("settings-actions")
            .frame(egui::Frame::new().inner_margin(egui::Margin {
                top: 16,
                bottom: 0,
                left: 0,
                right: 0,
            }))
            .show(ui, |ui| self.footer(ui));
        egui::Panel::top("settings-heading")
            .frame(egui::Frame::new().inner_margin(egui::Margin {
                bottom: 22,
                top: 0,
                left: 0,
                right: 0,
            }))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.vertical(|ui| {
                        ui.label(
                            egui::RichText::new("NANOLEAF / KDE")
                                .size(11.0)
                                .strong()
                                .color(ACCENT),
                        );
                        ui.heading("Screen Mirror");
                        ui.label(
                            egui::RichText::new("Light that follows your screen.").color(MUTED),
                        );
                    });
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(
                            egui::RichText::new(format!("v{}", env!("CARGO_PKG_VERSION")))
                                .color(MUTED),
                        );
                    });
                });
            });
        egui::Panel::left("settings-navigation")
            .exact_size(180.0)
            .resizable(false)
            .show_separator_line(false)
            .frame(egui::Frame::new().inner_margin(egui::Margin {
                right: 20,
                left: 0,
                top: 0,
                bottom: 0,
            }))
            .show(ui, |ui| {
                ui.label(egui::RichText::new("YOUR LIGHTING").small().color(MUTED));
                for (page, title, subtitle) in [
                    (Page::Mirror, "Mirroring", "Everyday controls"),
                    (Page::Strip, "Strip setup", "Mapping & test colours"),
                    (Page::Colour, "Colour calibration", "Measured profiles"),
                    (Page::Advanced, "Advanced", "Capture & diagnostics"),
                ] {
                    let text = egui::RichText::new(title).strong();
                    if ui
                        .add_sized(
                            [158.0, 40.0],
                            egui::Button::new(text).selected(self.page == page),
                        )
                        .on_hover_text(subtitle)
                        .clicked()
                    {
                        self.page = page;
                    }
                }
                ui.add_space(24.0);
                ui.separator();
                ui.label(
                    egui::RichText::new("ONE SCREEN. ONE STRIP.")
                        .size(10.0)
                        .color(MUTED),
                );
                ui.label(if self.draft.device_zone_count == 0 {
                    "Strip setup needed".to_string()
                } else {
                    format!("{} manual zones", self.draft.device_zone_count)
                });
                ui.small("Closing Settings keeps the tray available.");
            });
        egui::ScrollArea::vertical()
            .id_salt(match self.page {
                Page::Mirror => "mirror",
                Page::Strip => "strip",
                Page::Colour => "colour",
                Page::Advanced => "advanced",
            })
            .auto_shrink([false, false])
            .show(ui, |ui| {
                match self.page {
                    Page::Mirror => self.mirror(ui),
                    Page::Strip => self.strip(ui),
                    Page::Colour => self.colour(ui),
                    Page::Advanced => self.advanced(ui),
                }
                ui.add_space(12.0);
            });
    }

    fn footer(&mut self, ui: &mut egui::Ui) {
        ui.separator();
        ui.horizontal(|ui| {
            let button = egui::Button::new(
                egui::RichText::new("Save / Apply")
                    .strong()
                    .color(egui::Color32::from_rgb(15, 37, 29)),
            )
            .fill(ACCENT);
            if ui.add(button).clicked() {
                self.save();
            }
            if ui
                .button("Reload saved")
                .on_hover_text("Discard draft changes and reload saved settings")
                .clicked()
            {
                match Store::load(&self.store.path) {
                    Ok(store) => {
                        self.draft = store.config.clone();
                        self.store = store;
                        self.message = "Saved settings reloaded.".into();
                    }
                    Err(error) => self.message = error.to_string(),
                }
            }
            let changed = serde_json::to_value(&self.draft).ok()
                != serde_json::to_value(&self.store.config).ok();
            ui.label(
                egui::RichText::new(if changed {
                    "Unsaved changes"
                } else {
                    "Settings saved"
                })
                .color(if changed { ACCENT } else { MUTED }),
            );
        });
        if !self.message.is_empty() {
            ui.label(&self.message);
        } else {
            ui.label(
                egui::RichText::new("Applies changes and keeps this window open.")
                    .small()
                    .color(MUTED),
            );
        }
    }

    fn mirror(&mut self, ui: &mut egui::Ui) {
        card(
            ui,
            "Your mirror",
            "Screen-edge colour, calibrated for your strip.",
            |ui| {
                let running = self.status.as_ref().is_some_and(|status| status.running);
                let preview = self.status.as_ref().is_some_and(|status| status.preview);
                let (label, colour) = if running {
                    ("Mirroring", ACCENT)
                } else if preview {
                    ("Test colour active", ACCENT)
                } else {
                    ("Stopped", MUTED)
                };
                ui.label(egui::RichText::new(label).size(21.0).strong().color(colour));
                if let Some(status) = &self.status {
                    ui.label(&status.message);
                    if running {
                        ui.small(format!(
                            "{} · {:.1} acknowledged updates/s",
                            status.model, status.effective_fps
                        ));
                    }
                } else {
                    ui.label("Open Nanoleaf Screen Mirror from KDE's application launcher to start the tray.");
                }
                ui.horizontal(|ui| {
                    let ready = self.preview_settings_ready
                        && self.status.is_some()
                        && crate::pipeline::validate_mirroring(&self.store.config).is_ok()
                        && !running;
                    if ui
                        .add_enabled(ready, egui::Button::new("Start mirroring"))
                        .clicked()
                    {
                        self.control(Control::Start);
                    }
                    if ui
                        .add_enabled(running || preview, egui::Button::new("Stop mirroring"))
                        .clicked()
                    {
                        self.control(Control::Stop);
                    }
                });
            },
        );
        if let Err(error) = crate::pipeline::validate_mirroring(&self.draft) {
            let setup = onboarding::needs_setup(&self.draft);
            card(
                ui,
                if setup {
                    "Let's set up your strip"
                } else {
                    "Settings need attention"
                },
                if setup {
                    "A few details make the light follow the right edges."
                } else {
                    "Review these settings before starting mirroring."
                },
                |ui| {
                    ui.label(error.to_string());
                    if setup {
                        ui.small("Set the manual zone count, locate the four corners, then save your mapping.");
                    }
                    if ui
                        .button(if setup {
                            "Begin strip setup"
                        } else {
                            "Open Advanced"
                        })
                        .clicked()
                    {
                        self.page = if setup { Page::Strip } else { Page::Advanced };
                    }
                },
            );
        }
        card(
            ui,
            "Screen & appearance",
            "Choose what to mirror and how bright it feels.",
            |ui| {
                ui.label(egui::RichText::new("Selected screen").strong());
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
                            ui.selectable_value(
                                &mut self.draft.capture_monitor,
                                name.clone(),
                                name,
                            );
                        }
                    });
                if !self.draft.capture_monitor.is_empty()
                    && !self.screens.contains(&self.draft.capture_monitor)
                {
                    ui.small(
                "The saved screen is unavailable. It will be retried without switching screens.",
            );
                }
                ui.add(
                    egui::Slider::new(&mut self.draft.brightness, 0.0..=1.0)
                        .custom_formatter(|value, _| format!("{:.0}%", value * 100.0))
                        .custom_parser(|text| {
                            text.trim()
                                .trim_end_matches('%')
                                .parse::<f64>()
                                .ok()
                                .map(|value| value / 100.0)
                        })
                        .text("Brightness"),
                );
                ui.add(egui::Slider::new(&mut self.draft.fps, 1..=240).text("Target FPS"));
                choice(
                    ui,
                    "Colour style",
                    &mut self.draft.color_style,
                    &["reference", "natural", "ambient", "vivid", "punchy"],
                );
            },
        );
        card(
            ui,
            "Response & startup",
            "Tune the feel without changing your calibration.",
            |ui| {
                ui.add(
                    egui::Slider::new(&mut self.draft.smoothing, 0.0..=1.0).text("Response speed"),
                );
                ui.add(
                    egui::Slider::new(&mut self.draft.smoothing_speed, 0.0..=4.0)
                        .text("Motion response"),
                );
                if ui.button("Use fast response").clicked() {
                    self.draft.enable_fast_response();
                    self.message = "Fast response selected. Save / Apply to use it.".into();
                }
                ui.small(
            "Fast response follows changes promptly; small colour variations may be more visible.",
        );
                if self.draft.zone_temporal_accumulation {
                    ui.small(
                        "Additional temporal averaging is enabled and can delay colour changes.",
                    );
                }
                ui.checkbox(
                    &mut self.draft.letterbox_detection,
                    "Follow content inside black bars",
                );
                ui.checkbox(
                    &mut self.draft.start_on_launch,
                    "Start mirroring when the tray launches",
                );
            },
        );
    }

    fn strip(&mut self, ui: &mut egui::Ui) {
        ui.label(egui::RichText::new("Make it yours").size(25.0).strong());
        ui.label(
            egui::RichText::new("A guided setup for one screen and one USB strip.").color(MUTED),
        );
        ui.horizontal_wrapped(|ui| {
            for (index, step) in Step::ALL.into_iter().enumerate() {
                let selected = step == self.setup_step;
                ui.label(
                    egui::RichText::new(format!("{}  {}", index + 1, step.title()))
                        .color(if selected { ACCENT } else { MUTED })
                        .strong(),
                );
                if index < 3 {
                    ui.label(egui::RichText::new("/").color(MUTED));
                }
            }
        });
        match self.setup_step {
            Step::Connect => self.setup_connection(ui),
            Step::Corners => self.setup_corners(ui),
            Step::Colours => self.setup_colours(ui),
            Step::Ready => self.setup_ready(ui),
        }
        if self.status.as_ref().is_some_and(|status| status.preview)
            && ui.button("Clear test colour").clicked()
        {
            self.control(Control::Stop);
        }
        ui.add_space(4.0);
        if let Some(previous) = self.setup_step.previous() {
            if ui.button("Back").clicked() {
                self.setup_step = previous;
            }
        }
    }

    fn setup_connection(&mut self, ui: &mut egui::Ui) {
        card(
            ui,
            "Connect your strip",
            "Plug in the USB data cable and close other strip-control apps.",
            |ui| {
                ui.small("Your existing calibration stays in place. Setup only changes the values you edit.");
                egui::ComboBox::from_label("Strip model")
                    .selected_text(if self.draft.device_pid == 0x8201 {
                        "NL82K1"
                    } else {
                        "NL82K2"
                    })
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut self.draft.device_pid, 0x8201, "NL82K1");
                        ui.selectable_value(&mut self.draft.device_pid, 0x8202, "NL82K2");
                    });
                ui.horizontal(|ui| {
                    ui.label("Manual zone count");
                    ui.add(
                        egui::DragValue::new(&mut self.draft.device_zone_count)
                            .range(0..=512)
                            .speed(1.0),
                    );
                });
                ui.small("Enter the number of independently controlled zones on your strip (4–512). This is never guessed or replaced by detection.");
                egui::ComboBox::from_id_salt("setup-monitor")
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
                        for screen in &self.screens {
                            ui.selectable_value(
                                &mut self.draft.capture_monitor,
                                screen.clone(),
                                screen,
                            );
                        }
                    });
                ui.small("Choose the screen whose edges the strip follows. Advanced retains your capture backend.");
                if ui.button("Check USB connection").clicked() {
                    self.usb_check = Some(match hidapi::HidApi::new() {
                        Ok(hid) => {
                            let connected = hid.device_list().any(|device| {
                                device.vendor_id() == 0x37fa
                                    && device.product_id() == self.draft.device_pid
                            });
                            if connected {
                                "Your selected strip model is connected. Access to output is checked when you test a colour.".into()
                            } else {
                                "Selected strip not found. Check the model and USB data cable, then try again. USB permissions may need the supplied udev rule.".into()
                            }
                        }
                        Err(error) => format!("Connection check unavailable: {error}"),
                    });
                }
                if let Some(message) = &self.usb_check {
                    ui.label(message);
                }
                ui.separator();
                if ui
                    .add_enabled(
                        (4..=512).contains(&self.draft.device_zone_count),
                        egui::Button::new("Save count & continue"),
                    )
                    .clicked()
                    && self.save()
                {
                    self.setup_step = Step::Corners;
                }
                ui.small("Setup pauses mirroring. Test colours run only when you choose them.");
            },
        );
    }

    fn setup_corners(&mut self, ui: &mut egui::Ui) {
        card(
            ui,
            "Find the four corners",
            "Locate a zone, then record the corner nearest that light.",
            |ui| {
                self.preview_zone = self
                    .preview_zone
                    .min(self.draft.device_zone_count.saturating_sub(1));
                let can_locate = self.preview_settings_ready
                    && self.status.is_some()
                    && onboarding::can_locate(&self.store.config, &self.draft);
                ui.horizontal(|ui| {
                    ui.label("Preview zone");
                    ui.add(
                        egui::DragValue::new(&mut self.preview_zone)
                            .range(0..=self.draft.device_zone_count.saturating_sub(1)),
                    );
                    if ui
                        .add_enabled(can_locate, egui::Button::new("Locate zone"))
                        .clicked()
                    {
                        self.control(Control::Preview {
                            rgb: [80; 3],
                            zone: Some(self.preview_zone),
                        });
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    if ui
                        .add_enabled(
                            can_locate && self.preview_zone > 0,
                            egui::Button::new("Previous zone"),
                        )
                        .clicked()
                    {
                        self.preview_zone -= 1;
                        self.control(Control::Preview {
                            rgb: [80; 3],
                            zone: Some(self.preview_zone),
                        });
                    }
                    if ui
                        .add_enabled(
                            can_locate && self.preview_zone + 1 < self.draft.device_zone_count,
                            egui::Button::new("Next zone"),
                        )
                        .clicked()
                    {
                        self.preview_zone += 1;
                        self.control(Control::Preview {
                            rgb: [80; 3],
                            zone: Some(self.preview_zone),
                        });
                    }
                });
                self.corner_diagram(ui);
                egui::Grid::new("setup-anchors")
                    .num_columns(3)
                    .spacing([14.0, 8.0])
                    .show(ui, |ui| {
                        for (label, anchor) in [
                            (
                                "Top left",
                                &mut self.draft.calibration.corner_anchor_top_left,
                            ),
                            (
                                "Top right",
                                &mut self.draft.calibration.corner_anchor_top_right,
                            ),
                            (
                                "Bottom right",
                                &mut self.draft.calibration.corner_anchor_bottom_right,
                            ),
                            (
                                "Bottom left",
                                &mut self.draft.calibration.corner_anchor_bottom_left,
                            ),
                        ] {
                            ui.label(label);
                            ui.add(
                                egui::DragValue::new(anchor).range(
                                    -1..=self.draft.device_zone_count.saturating_sub(1) as i64,
                                ),
                            );
                            if ui
                                .button(format!("Use zone {}", self.preview_zone))
                                .clicked()
                            {
                                *anchor = self.preview_zone as i64;
                            }
                            ui.end_row();
                        }
                    });
                if !can_locate {
                    ui.small("Save the strip count, model and channel order before testing. The tray must be running.");
                }
                ui.small("Zone numbering starts at 0. Each corner needs a different zone. A locate test pauses mirroring and clears after ten seconds.");
                if ui
                    .add_enabled(
                        !onboarding::needs_setup(&self.draft),
                        egui::Button::new("Save corners & continue"),
                    )
                    .clicked()
                    && self.save()
                {
                    self.setup_step = Step::Colours;
                }
            },
        );
    }

    fn corner_diagram(&self, ui: &mut egui::Ui) {
        let (rect, _) = ui.allocate_exact_size(
            egui::vec2(ui.available_width(), 126.0),
            egui::Sense::hover(),
        );
        let screen = rect.shrink2(egui::vec2(44.0, 16.0));
        let painter = ui.painter();
        painter.rect_filled(screen, 10, egui::Color32::from_rgb(17, 25, 27));
        painter.rect_stroke(
            screen,
            10,
            egui::Stroke::new(2.0, ACCENT),
            egui::StrokeKind::Inside,
        );
        painter.text(
            screen.center(),
            egui::Align2::CENTER_CENTER,
            "Your screen",
            egui::FontId::proportional(14.0),
            MUTED,
        );
        for (position, value) in [
            (
                screen.left_top(),
                self.draft.calibration.corner_anchor_top_left,
            ),
            (
                screen.right_top(),
                self.draft.calibration.corner_anchor_top_right,
            ),
            (
                screen.right_bottom(),
                self.draft.calibration.corner_anchor_bottom_right,
            ),
            (
                screen.left_bottom(),
                self.draft.calibration.corner_anchor_bottom_left,
            ),
        ] {
            painter.circle_filled(position, 13.0, egui::Color32::from_rgb(46, 77, 65));
            painter.text(
                position,
                egui::Align2::CENTER_CENTER,
                if value < 0 {
                    "?".into()
                } else {
                    value.to_string()
                },
                egui::FontId::proportional(12.0),
                egui::Color32::WHITE,
            );
        }
    }

    fn setup_colours(&mut self, ui: &mut egui::Ui) {
        card(
            ui,
            "Check the colour order",
            "Use the test colours to confirm the strip matches the labels.",
            |ui| {
                choice(
                    ui,
                    "Strip channel order",
                    &mut self.draft.output_channel_order,
                    &["grb", "rgb", "rbg", "gbr", "brg", "bgr"],
                );
                ui.checkbox(&mut self.draft.reverse_zones, "Reverse strip order");
                let can_preview = self.preview_settings_ready
                    && self.status.is_some()
                    && onboarding::can_locate(&self.store.config, &self.draft);
                ui.add_enabled_ui(can_preview, |ui| {
                    ui.horizontal_wrapped(|ui| {
                        for (label, rgb, swatch) in [
                            ("Red", [80, 0, 0], egui::Color32::from_rgb(205, 78, 84)),
                            ("Green", [0, 80, 0], egui::Color32::from_rgb(59, 147, 104)),
                            ("Blue", [0, 0, 80], egui::Color32::from_rgb(63, 117, 193)),
                            ("Grey", [64; 3], egui::Color32::from_gray(90)),
                            ("Black", [0; 3], egui::Color32::from_gray(23)),
                        ] {
                            if ui
                                .add(
                                    egui::Button::new(
                                        egui::RichText::new(label).color(egui::Color32::WHITE),
                                    )
                                    .fill(swatch),
                                )
                                .clicked()
                            {
                                self.control(Control::Preview { rgb, zone: None });
                            }
                        }
                    });
                });
                if !can_preview {
                    ui.label("Save / Apply any channel-order changes before testing. The tray must be running.");
                }
                ui.label("Red, green and blue should match. Grey should look neutral and black should turn the strip off.");
                ui.small("Each test pauses mirroring and clears after ten seconds. Use Stop mirroring to clear a test immediately.");
                ui.label("For measured gains and white balance, use Colour calibration. Existing profiles are preserved.");
                if ui.button("Save colour settings & continue").clicked() && self.save() {
                    self.setup_step = Step::Ready;
                }
            },
        );
    }

    fn setup_ready(&mut self, ui: &mut egui::Ui) {
        card(ui, "Ready when you are", "Your mapping is saved. Start mirroring when you want the lights to follow your screen.", |ui| {
            ui.label(format!("{} · {} manual zones", if self.draft.device_pid == 0x8201 { "NL82K1" } else { "NL82K2" }, self.draft.device_zone_count));
            ui.label(format!("Screen: {}", if self.draft.capture_monitor.is_empty() { "Active screen" } else { &self.draft.capture_monitor }));
            ui.label(format!("Corner zones: {} / {} / {} / {}", self.draft.calibration.corner_anchor_top_left, self.draft.calibration.corner_anchor_top_right, self.draft.calibration.corner_anchor_bottom_right, self.draft.calibration.corner_anchor_bottom_left));
            if let Err(error) = onboarding::ready(&self.draft) { ui.label(error.to_string()); }
            let ready = onboarding::ready(&self.draft).is_ok();
            ui.horizontal_wrapped(|ui| {
                if ui.add_enabled(ready, egui::Button::new("Finish setup")).clicked() && self.save() { self.page = Page::Mirror; }
                if ui.add_enabled(ready && self.status.is_some(), egui::Button::new("Save & start mirroring")).clicked() && self.save() && self.preview_settings_ready {
                    self.control(Control::Start); self.page = Page::Mirror;
                }
            });
            ui.small("Stop pauses the lights while keeping the tray available. Closing Settings also keeps the tray running.");
        });
    }

    fn colour(&mut self, ui: &mut egui::Ui) {
        card(
            ui,
            "Measured colour",
            "Fine-tune emitted light using your measured profile.",
            |ui| {
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
                            self.profile_action =
                                Some(ProfileAction::Export(preset.into(), profile));
                        }
                    });
                }

                ui.separator();
                ui.checkbox(&mut self.hdr_profile, "Edit HDR profile");
                if self.hdr_profile {
                    profile_ui(ui, &mut self.draft.led_calibration_profile_hdr);
                } else {
                    profile_ui(ui, &mut self.draft.led_calibration_profile_sdr);
                }
                ui.small("Screen capture is display-referred SDR, including on HDR desktops. Its SDR LED profile is applied; your separate HDR profile is retained.");
            },
        );
    }

    fn advanced(&mut self, ui: &mut egui::Ui) {
        card(
            ui,
            "Advanced / Troubleshooting",
            "Capture, login startup and detailed diagnostics.",
            |ui| {
                ui.horizontal(|ui| {
                    if ui.button("Launch native tray at login").clicked() {
                        self.message = crate::package::autostart(true)
                            .map(|_| "Native tray login launch enabled.".into())
                            .unwrap_or_else(|e| e.to_string());
                    }
                    if ui.button("Disable native login launch").clicked() {
                        self.message = crate::package::autostart(false)
                            .map(|_| "Native login launch disabled.".into())
                            .unwrap_or_else(|e| e.to_string());
                    }
                });
                choice(
                    ui,
                    "Capture",
                    &mut self.draft.capture_backend,
                    &["auto", "kwin-dbus", "xdg-portal"],
                );
                ui.small("Streaming uses the portal permission and a separate capture worker. Automatic capture uses KWin. Your selected backend is preserved.");
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
            if let Some(s)=&self.status{ui.separator();ui.label(format!("Capture {:.2} ms · colour {:.2} ms · USB {:.2} ms",s.capture_ms,s.processing_ms,s.usb_ms));ui.label(format!("Software response {:.2} ms · {} acknowledged packets · {} missed deadlines",s.response_ms,s.frames,s.missed_deadlines));ui.small("Response runs from capture request or stream sampling work to USB acknowledgement; emitted-light delay is not measured.");ui.small(match s.response_clock.as_str(){"capture-work"=>"Timing starts when the stream frame begins processing.","cached-work"=>"Timing starts when the unchanged image is reprocessed.","source-presentation"=>"Legacy timing starts at the display presentation marker.",_=>"Timing starts at capture or processing."});if let Some(age)=s.source_presentation_age_ms{ui.small(format!("Compositor PTS age {:.2} ms (software metadata, separate from capture latency)",age));}ui.small(format!("{} inferred packets (included in acknowledged packets)",s.predicted_frames));ui.label(format!("Manual {} · reported {} · connections {}",s.manual_zones,s.reported_zones,s.reconnects));ui.label(&s.backend);}
            if let Some(t)=self.status.as_ref().and_then(|s|s.capture_stages.as_ref()) {
                ui.small(format!("Capture breakdown: wait {:.2} ms · import {:.2} ms · image analysis {:.2} ms · sampling {:.2} ms · release {:.2} ms",t.producer_fence_ms,t.import_ms,t.analysis_ms,t.sampling_ms,t.release_ms));
            }
            if let Some(ms)=self.status.as_ref().and_then(|s|s.response_to_write_ms) { ui.small(format!("Capture work to final USB write: {:.2} ms (host completion; light timing unknown)",ms)); }
            if let Some(t)=self.status.as_ref().and_then(|s|s.usb_transaction.as_ref()) {
                ui.small(format!("Last USB packet: drain {:.3} ms · write {:.3} ms · wait for acknowledgement {:.3} ms",t.drain_ms,t.write_ms,t.ack_wait_ms));
                ui.small(format!("First response after {:.3} ms · {} reports written / {} received",t.first_report_wait_ms,t.written_reports,t.response_reports));
            }
            if let Some(s)=&self.status {
                if s.short_updates_enabled {
                    if let Some(t) = &s.usb_transaction {
                        ui.small(format!("USB colour payload: {} of {} zones · {} acknowledged updates shortened", t.sent_zones,s.manual_zones,s.shortened_packets));
                    }
                    ui.small("Only an exactly unchanged tail is retained. Every update is acknowledged; dither phases still advance.");
                }
                if let Some(timing) = &s.response_summary {
                    for (label, window) in [("Fresh screen updates", &timing.fresh), ("Repeated image updates", &timing.cached)] {
                        if window.samples > 0 {
                            ui.separator();
                            ui.small(format!("{label}: latest {} of {} measured packets", window.samples, window.observed));
                            ui.small(format!("Work to USB write: usual {:.2} ms · 95% within {:.2} ms · 99% within {:.2} ms", window.to_write_ms.p50, window.to_write_ms.p95, window.to_write_ms.p99));
                            ui.small(format!("95% within: waiting to send {:.2} ms · USB transaction {:.2} ms · work to acknowledgement {:.2} ms", window.queue_ms.p95, window.usb_ms.p95, window.to_ack_ms.p95));
                        }
                    }
                    ui.small("Software timings only; recent packets since Start, Apply or USB reconnection. Preview and inferred packets are excluded.");
                }
                ui.small(format!("{} packets reprocessed from an unchanged shared image; these are not new captured frames.",s.reused_source_packets));
                if s.last_source_reused {ui.small("Last response timing starts at unchanged-image processing, not the original capture timestamp.");}
            }
            });
            },
        );
    }
    fn draft_document(&self) -> toml_edit::DocumentMut {
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
            (
                "zone_box_filter_sampling",
                self.draft.zone_box_filter_sampling,
            ),
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
        doc
    }

    fn save(&mut self) -> bool {
        let setup_changed = self.page == Page::Strip
            || !onboarding::can_locate(&self.store.config, &self.draft)
            || self.store.config.anchors() != self.draft.anchors();
        let doc = self.draft_document();
        let saved = self.store.save_document(doc);
        let success = saved.is_ok();
        self.message = match saved {
            Ok(()) => {
                self.draft = self.store.config.clone();
                self.last_poll = Instant::now() - Duration::from_secs(2);
                // An incomplete setup must be loaded while stopped. The actor
                // handles Stop, Reload and any later Preview in command order.
                // Otherwise a running actor can reject the partial mapping and
                // a preview would still use its old strip geometry.
                self.preview_settings_ready = false;
                let stopped = !setup_changed || service::send(&Control::Stop).is_ok();
                if stopped && service::send(&Control::Reload).is_ok() {
                    self.preview_settings_ready = true;
                    "Settings saved; reload requested. A backup is retained.".into()
                } else {
                    "Settings saved. Open the tray, then Save / Apply before testing or starting. A backup is retained.".into()
                }
            }
            Err(e) => e.to_string(),
        };
        success
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> Settings {
        let store = Store::parse(
            Path::new("unused.toml"),
            b"schema_version=2\nunknown_setting='preserve'\n[led_calibration_profile_sdr]\nred_gain=0.42\n".to_vec(),
        ).unwrap();
        Settings {
            draft: store.config.clone(),
            store,
            message: String::new(),
            page: Page::Mirror,
            setup_step: Step::Connect,
            usb_check: None,
            preview_settings_ready: true,
            status: None,
            last_poll: Instant::now(),
            preview_zone: 0,
            screens: vec!["Test screen".into()],
            hdr_profile: false,
            picker: None,
            profile_action: None,
        }
    }

    #[test]
    fn navigating_every_settings_page_preserves_draft_and_saved_calibration() {
        let mut settings = settings();
        let original = serde_json::to_value(&settings.draft).unwrap();
        let original_document = settings.store.document.to_string();
        let context = egui::Context::default();
        configure_style(&context);
        for (page, step) in [
            (Page::Mirror, Step::Connect),
            (Page::Strip, Step::Connect),
            (Page::Strip, Step::Corners),
            (Page::Strip, Step::Colours),
            (Page::Strip, Step::Ready),
            (Page::Colour, Step::Connect),
            (Page::Advanced, Step::Connect),
        ] {
            settings.page = page;
            settings.setup_step = step;
            let mut output = context.run_ui(
                egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        egui::Pos2::ZERO,
                        egui::vec2(760.0, 620.0),
                    )),
                    ..Default::default()
                },
                |ui| settings.layout(ui),
            );
            output.textures_delta.clear();
            assert_eq!(serde_json::to_value(&settings.draft).unwrap(), original);
            assert_eq!(settings.store.document.to_string(), original_document);
        }
    }

    #[test]
    fn full_area_box_sampling_edit_is_saved_and_unknown_fields_survive() {
        let mut settings = settings();
        settings.draft.zone_box_filter_sampling = !settings.draft.zone_box_filter_sampling;
        settings.draft.brightness = 0.37;
        let document = settings.draft_document();
        let reloaded =
            Store::parse(Path::new("unused.toml"), document.to_string().into_bytes()).unwrap();
        assert_eq!(
            reloaded.config.zone_box_filter_sampling,
            settings.draft.zone_box_filter_sampling
        );
        assert_eq!(reloaded.config.brightness, 0.37);
        assert_eq!(reloaded.config.led_calibration_profile_sdr.red_gain, 0.42);
        assert_eq!(
            reloaded.document["unknown_setting"].as_str(),
            Some("preserve")
        );
    }
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
