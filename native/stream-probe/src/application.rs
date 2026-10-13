//! Capture child only: emits small prepared colour frames; the tray actor owns HID.
use anyhow::{ensure, Context, Result};
use nanoleaf_core::sampling::ZoneRect;
use nanoleaf_native::{
    capture::Frame,
    config::Config,
    geometry,
    pipeline::{self, Pipeline},
};
use pipewire::spa;
use std::{
    io::{BufRead, Read, Write},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Instant,
};
pub struct Application {
    pub config: Config,
    pipeline: Pipeline,
    shadow: Option<Pipeline>,
    sent: Arc<Mutex<Vec<[u8; 3]>>>,
    stop: Arc<AtomicBool>,
}
impl Application {
    pub fn new(config: Config) -> Result<Self> {
        pipeline::validate_mirroring(&config)?;
        let sent = Arc::new(Mutex::new(Vec::new()));
        let stop = Arc::new(AtomicBool::new(false));
        let (received, cancel) = (sent.clone(), stop.clone());
        let count = config.device_zone_count;
        std::thread::spawn(move || {
            let input = std::io::stdin();
            let mut input = input.lock();
            loop {
                let mut line = String::new();
                match input.by_ref().take(32769).read_line(&mut line) {
                    Ok(0) => break,
                    Ok(_) if line.len() <= 32768 => {}
                    _ => break,
                }
                let Ok(ack) = serde_json::from_str::<Vec<[u8; 3]>>(&line) else {
                    break;
                };
                if ack.len() != count {
                    break;
                }
                if let Ok(mut slot) = received.lock() {
                    *slot = ack;
                }
            }
            cancel.store(true, Ordering::Release);
        });
        Ok(Self {
            config,
            pipeline: Pipeline::default(),
            shadow: std::env::var_os("NANOLEAF_STREAM_PARITY").map(|_| Pipeline::default()),
            sent,
            stop,
        })
    }
    pub fn parity(&self) -> bool {
        self.shadow.is_some()
    }
    pub fn cancelled(&self) -> bool {
        self.stop.load(Ordering::Acquire)
    }
    pub fn zones(&self, width: usize, height: usize) -> Result<Vec<ZoneRect>> {
        let full = pipeline::ContentBounds {
            left: 0,
            top: 0,
            right: width,
            bottom: height,
        };
        if let Ok(plan) = pipeline::direct_plan_with_bounds(&self.config, width, height, Some(full))
        {
            Ok(plan.zones)
        } else {
            Ok(geometry::pixel_zones(&self.config, width, height)?.0)
        }
    }
    pub fn needs_pixels(&self, width: usize, height: usize) -> bool {
        pipeline::direct_plan_with_bounds(
            &self.config,
            width,
            height,
            Some(pipeline::ContentBounds {
                left: 0,
                top: 0,
                right: width,
                bottom: height,
            }),
        )
        .is_err()
    }
    pub fn plan(
        &self,
        width: usize,
        height: usize,
        reader: &mut nanoleaf_linux_gpu::RegionReader<'_>,
    ) -> Result<(Vec<ZoneRect>, Option<pipeline::ContentBounds>)> {
        let bounds = if self.config.letterbox_detection {
            let reader = std::cell::RefCell::new(reader);
            Some(pipeline::detect_content_bounds(
                width,
                height,
                |y| pipeline::encoded_mean(&reader.borrow_mut().row(y as u32)?),
                |x, top, bottom| {
                    pipeline::encoded_mean(&reader.borrow_mut().column(
                        x as u32,
                        top as u32,
                        bottom as u32,
                    )?)
                },
            )?)
        } else {
            None
        };
        let plan = pipeline::direct_plan_with_bounds(&self.config, width, height, bounds)?;
        Ok((plan.zones, bounds))
    }
    pub fn frame(
        &mut self,
        width: usize,
        height: usize,
        sampled: nanoleaf_linux_gpu::SampledFrame,
        bounds: Option<pipeline::ContentBounds>,
        header: Option<&spa::buffer::meta::MetaHeader>,
        started: Instant,
    ) -> Result<()> {
        if let Ok(sent) = self.sent.lock() {
            if !sent.is_empty() {
                self.pipeline.override_sent(&sent);
                if let Some(shadow) = &mut self.shadow {
                    shadow.override_sent(&sent);
                }
            }
        }
        let capture_ms = started.elapsed().as_secs_f64() * 1000.0;
        let pixel_path = self.needs_pixels(width, height);
        let mut diagnostic = sampled.diagnostic_rgb;
        let output = if pixel_path {
            let rgb = diagnostic
                .take()
                .context("Pixel policy has no capture pixels")?;
            self.pipeline.process(
                &Frame {
                    width,
                    height,
                    pixels: rgb,
                },
                &self.config,
            )?
        } else {
            self.pipeline.process_sdr_samples_with_bounds(
                width,
                height,
                &sampled.samples,
                &self.config,
                bounds,
            )?
        };
        let parity_exact = if let Some(shadow) = &mut self.shadow {
            if !pixel_path {
                let rgb = diagnostic
                    .take()
                    .context("Parity check has no reference pixels")?;
                let reference = shadow.process(
                    &Frame {
                        width,
                        height,
                        pixels: rgb,
                    },
                    &self.config,
                )?;
                ensure!(
                    reference.sampled == output.sampled
                        && reference.colors == output.colors
                        && reference.modes == output.modes
                        && reference.unquantized_rgb == output.unquantized_rgb,
                    "Complete GPU/CPU colour pipeline parity failed"
                );
                Some(true)
            } else {
                None
            }
        } else {
            None
        };
        let age = super::pts_age(header).unwrap_or(capture_ms + output.times.total_ms);
        let backend = if pixel_path {
            "xdg-portal / Vulkan DMA-BUF / CPU pixel policies"
        } else {
            "xdg-portal / Vulkan DMA-BUF / direct SDR samples"
        };
        let record = serde_json::json!({"schema":1,"colors":output.colors,"unquantized_rgb":output.unquantized_rgb,"times":output.times,"capture_ms":capture_ms,"prepared_age_ms":age,"source_pts_ns":header.map(|h|h.pts()),"backend":backend,"parity_exact":parity_exact,"highlight_cache":output.highlight_cache});
        let stdout = std::io::stdout();
        let mut stdout = stdout.lock();
        serde_json::to_writer(&mut stdout, &record)?;
        stdout.write_all(b"\n")?;
        stdout.flush()?;
        Ok(())
    }
}
pub fn run() -> Result<()> {
    // This pilot's untagged RGB8 contract is pinned to the researched KWin family.
    // Other compositors or raw HDR require explicit metadata validation first.
    let connection = zbus::blocking::connection::Builder::session()?
        .method_timeout(std::time::Duration::from_secs(2))
        .build()?;
    let kwin = zbus::blocking::Proxy::new(&connection, "org.kde.KWin", "/KWin", "org.kde.KWin")?;
    let info: String = kwin.call("supportInformation", &())?;
    let version = info
        .lines()
        .find_map(|l| l.strip_prefix("KWin version: "))
        .context("Cannot establish KWin colour contract")?;
    ensure!(
        version.starts_with("6.7."),
        "This experimental stream colour contract is verified for KWin 6.7 only"
    );
    let mut initial = String::new();
    std::io::stdin()
        .lock()
        .take(1_048_577)
        .read_line(&mut initial)?;
    ensure!(
        initial.len() <= 1_048_576,
        "Oversized capture configuration"
    );
    let config: Config = serde_json::from_str(&initial)?;
    let application = Application::new(config)?;
    let prepared = super::gpu::prepare()?;
    let (session, fd) = super::portal::Session::open()?;
    let outputs = nanoleaf_native::screens::outputs()?;
    if let Err(error) = nanoleaf_native::screens::selected(
        &outputs,
        session.position,
        session.size,
        &application.config.capture_monitor,
    ) {
        crate::permission::Permission::user()?.invalidate()?;
        return Err(error);
    }
    let result = super::run_application(
        &session,
        fd,
        super::Mode::Dma,
        Some(&prepared),
        Some(application),
    )?;
    ensure!(
        result["errors"].as_array().is_some_and(Vec::is_empty),
        "Stream capture stopped: {}",
        result["errors"]
    );
    Ok(())
}
