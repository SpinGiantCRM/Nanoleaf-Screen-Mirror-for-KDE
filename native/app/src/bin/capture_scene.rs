//! Bounded, repeatable SDR workload for capture profiling. No capture or USB.
use anyhow::{ensure, Context, Result};
use eframe::egui;
use nanoleaf_native::{config::Store, screens};
use std::{
    path::Path,
    time::{Duration, Instant},
};

// Keep every edge well above the letterbox threshold, and use exactly the same
// repeating sequence in each run. These are requested sRGB codes, not a claim
// about scanout, HDR luminance, or the monitor's emitted light.
fn level(tick: u64) -> u8 {
    let phase = (tick % 240) as u16;
    let triangle = if phase <= 120 { phase } else { 240 - phase };
    (64 + triangle * 128 / 120) as u8
}

struct Scene {
    steps: bool,
    epoch: Option<Instant>,
    duration: Duration,
    paints: u64,
    last_tick: Option<u64>,
    unique_ticks: u64,
    completed: bool,
    invalid_viewport_paints: u64,
    last_paint: Option<Instant>,
    max_paint_gap_ms: f64,
    last_step: Option<u64>,
    step_requests: Vec<serde_json::Value>,
}

impl eframe::App for Scene {
    fn ui(&mut self, ui: &mut egui::Ui, _: &mut eframe::Frame) {
        let started = *self.epoch.get_or_insert_with(Instant::now);
        let elapsed = started.elapsed();
        let now = Instant::now();
        if elapsed >= Duration::from_secs(1) {
            let valid = ui.input(|i| {
                let v = i.viewport();
                v.focused == Some(true)
                    && v.fullscreen == Some(true)
                    && v.minimized != Some(true)
                    && v.occluded != Some(true)
            });
            if !valid {
                self.invalid_viewport_paints += 1;
            }
            if let Some(previous) = self.last_paint {
                self.max_paint_gap_ms = self
                    .max_paint_gap_ms
                    .max(now.duration_since(previous).as_secs_f64() * 1000.0);
            }
        }
        self.last_paint = Some(now);
        if elapsed >= self.duration || ui.input(|i| i.key_pressed(egui::Key::Escape)) {
            self.completed = elapsed >= self.duration;
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
        }
        let tick = (elapsed.as_nanos() * 120 / 1_000_000_000) as u64;
        self.paints += 1;
        if self.last_tick != Some(tick) {
            self.unique_ticks += 1;
            self.last_tick = Some(tick);
        }
        let rect = ui.max_rect();
        let grey = if self.steps {
            if elapsed.as_secs().is_multiple_of(2) {
                64
            } else {
                192
            }
        } else {
            level(tick)
        };
        if self.steps && self.last_step != Some(elapsed.as_secs()) {
            self.last_step = Some(elapsed.as_secs());
            self.step_requests.push(serde_json::json!({
                "elapsed_ns": elapsed.as_nanos(),
                "unix_ns": std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).expect("System clock before epoch").as_nanos(),
                "requested_grey_code": grey,
            }));
        }
        ui.painter()
            .rect_filled(rect, 0.0, egui::Color32::from_gray(grey));
        // A small changing centre marker guarantees damage during repeated
        // rounded grey codes without affecting the configured edge zones.
        let marker = egui::Rect::from_center_size(rect.center(), egui::vec2(32.0, 32.0));
        if !self.steps {
            ui.painter().rect_filled(
                marker,
                0.0,
                if tick.is_multiple_of(2) {
                    egui::Color32::BLACK
                } else {
                    egui::Color32::WHITE
                },
            );
        }
        if self.steps {
            ui.ctx().request_repaint_after(
                Duration::from_secs(1) - Duration::from_nanos(elapsed.subsec_nanos().into()),
            );
        } else {
            ui.ctx().request_repaint();
        }
    }
}

impl Drop for Scene {
    fn drop(&mut self) {
        println!(
            "{}",
            serde_json::json!({
                "scope": "Bounded synthetic SDR scene; counts are UI paint requests, not presentations or optical timing. No USB, capture, configuration writes or screen images.",
                "completed": self.completed,
                "elapsed_seconds": self.epoch.map(|t| t.elapsed().as_secs_f64()),
                "paint_requests": self.paints,
                "unique_logical_ticks": self.unique_ticks,
                "logical_hz": if self.steps { 1 } else { 120 },
                "invalid_viewport_paints_after_warmup": self.invalid_viewport_paints,
                "max_paint_gap_after_warmup_ms": self.max_paint_gap_ms,
                "step_paint_requests": self.step_requests,
                "pattern": if self.steps { "static neutral 64/192 steps each second; no continuous repaint" } else { "two-second neutral triangle 64..192 with centre marker" }
            })
        );
    }
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        (3..=4).contains(&args.len()),
        "Use capture_scene EXISTING_CONFIG SECONDS (1..180) [ramp|steps]; Escape closes early"
    );
    let pattern = args.get(3).map(String::as_str).unwrap_or("ramp");
    ensure!(matches!(pattern, "ramp" | "steps"), "Choose ramp or steps");
    let steps = pattern == "steps";
    let seconds: u64 = args[2].parse().context("Whole seconds required")?;
    ensure!(
        (1..=180).contains(&seconds),
        "Duration must be 1..180 seconds"
    );
    let config = Store::load(Path::new(&args[1]))?.config;
    let outputs = screens::outputs()?;
    ensure!(
        outputs.len() == 1,
        "The controlled scene requires exactly one connected monitor"
    );
    ensure!(
        config.capture_monitor.is_empty() || config.capture_monitor == outputs[0].name,
        "The connected monitor differs from the selected capture monitor"
    );
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_fullscreen(true)
            .with_decorations(false)
            .with_app_id("org.spingiantcrm.NanoleafCaptureScene"),
        ..Default::default()
    };
    eframe::run_native(
        "Nanoleaf bounded capture scene",
        options,
        Box::new(move |_| {
            Ok(Box::new(Scene {
                steps,
                epoch: None,
                duration: Duration::from_secs(seconds),
                paints: 0,
                last_tick: None,
                unique_ticks: 0,
                completed: false,
                invalid_viewport_paints: 0,
                last_paint: None,
                max_paint_gap_ms: 0.0,
                last_step: None,
                step_requests: Vec::new(),
            }))
        }),
    )
    .map_err(|e| anyhow::anyhow!(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn workload_is_bounded_neutral_repeatable_and_has_no_black_edges() {
        assert_eq!((level(0), level(120), level(240)), (64, 192, 64));
        for tick in 0..240 {
            assert!((64..=192).contains(&level(tick)));
            assert_eq!(level(tick), level(tick + 240));
            assert_eq!(level(tick), level((240 - tick) % 240));
        }
        assert_eq!(level(u64::MAX), level(u64::MAX % 240));
    }
}
