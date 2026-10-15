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
    time::{Duration, Instant},
};
pub struct Application {
    pub config: Config,
    pipeline: Pipeline,
    shadow: Option<Pipeline>,
    sent: Arc<Mutex<Vec<[u8; 3]>>>,
    stop: Arc<AtomicBool>,
    cached: Option<CachedSource>,
    last_output: Option<Instant>,
    temporal_clock: TemporalClock,
}
#[derive(Default)]
struct TemporalClock {
    work: Option<i64>,
}
impl TemporalClock {
    fn advance(&mut self, work_ns: i64) -> Option<Duration> {
        // KWin PTS is the display's last presentation, not this capture's time.
        // Use one monotonic sampling/work clock for fresh and cached processing:
        // a held PTS followed by a jump must not count elapsed time twice.
        let elapsed = self.work.map(|last| work_ns.saturating_sub(last).max(0));
        self.work = Some(self.work.map_or(work_ns, |last| work_ns.max(last)));
        elapsed.map(|ns| Duration::from_nanos(ns as u64))
    }
}
struct CachedSource {
    width: usize,
    height: usize,
    samples: Vec<nanoleaf_core::sampling::ZoneSample>,
    pixels: Option<Frame>,
    bounds: Option<pipeline::ContentBounds>,
    pts: Option<i64>,
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
            cached: None,
            last_output: None,
            temporal_clock: TemporalClock::default(),
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
        let bounds = if self.config.letterbox_detection && reader.uniform_dark()? {
            Some(pipeline::ContentBounds {
                left: 0,
                top: 0,
                right: width,
                bottom: height,
            })
        } else if self.config.letterbox_detection {
            let reader = std::cell::RefCell::new(reader);
            Some(pipeline::detect_content_bounds_by_decision(
                width,
                height,
                |y| {
                    let decision = reader
                        .borrow_mut()
                        .row_luma_above(y as u32, pipeline::CONTENT_THRESHOLD)?;
                    match decision {
                        Some(value) => Ok(value),
                        None => Ok(pipeline::encoded_mean(&reader.borrow_mut().row(y as u32)?)?
                            > pipeline::CONTENT_THRESHOLD),
                    }
                },
                |x, top, bottom| {
                    let decision = reader.borrow_mut().column_luma_above(
                        x as u32,
                        top as u32,
                        bottom as u32,
                        pipeline::CONTENT_THRESHOLD,
                    )?;
                    match decision {
                        Some(value) => Ok(value),
                        None => Ok(pipeline::encoded_mean(&reader.borrow_mut().column(
                            x as u32,
                            top as u32,
                            bottom as u32,
                        )?)? > pipeline::CONTENT_THRESHOLD),
                    }
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
        let t = &sampled.timings;
        let i = &t["interop"];
        let stages = nanoleaf_native::worker::CaptureStages {
            total_ms: t["complete_frame_ms"].as_f64().unwrap_or_default(),
            producer_fence_ms: i["producer_fence_ms"].as_f64().unwrap_or_default(),
            import_ms: i["import_or_cache_ms"].as_f64().unwrap_or_default(),
            acquire_ms: i["acquire_ms"].as_f64().unwrap_or_default(),
            analysis_ms: t["analysis_ms"].as_f64().unwrap_or_default(),
            zone_update_ms: t["zone_update_ms"].as_f64().unwrap_or_default(),
            sampling_ms: t["compute_readback_reduce_ms"].as_f64().unwrap_or_default(),
            release_ms: i["release_ms"].as_f64().unwrap_or_default(),
            cache_hit: i["cache_hit"].as_bool().unwrap_or_default(),
            analysis_bytes: t["analysis_rgb_bytes"].as_u64().unwrap_or_default(),
            analysis_summary_bytes: t["analysis_summary_bytes"].as_u64().unwrap_or_default(),
            analysis_batches: t["analysis_transfer_batches"].as_u64().unwrap_or_default(),
        };
        let source = CachedSource {
            width,
            height,
            samples: sampled.samples,
            pixels: sampled.diagnostic_rgb.map(|pixels| Frame {
                width,
                height,
                pixels,
            }),
            bounds,
            pts: header.map(|h| h.pts()),
        };
        let capture_ms = started.elapsed().as_secs_f64() * 1000.0;
        let mut record = self.process_source(&source, false, started, capture_ms)?;
        record["capture_stages"] = serde_json::to_value(stages)?;
        emit(&record)?;
        self.cached = Some(source);
        self.last_output = Some(Instant::now());
        Ok(())
    }
    pub fn invalidate(&mut self) {
        self.cached = None;
        self.last_output = None;
        self.temporal_clock = TemporalClock::default();
        self.pipeline = Pipeline::default();
        if self.shadow.is_some() {
            self.shadow = Some(Pipeline::default());
        }
    }
    fn repeat_record(&mut self, now: Instant) -> Result<Option<serde_json::Value>> {
        let period = Duration::from_secs_f64(1.0 / self.config.fps as f64);
        if self.cancelled()
            || self
                .last_output
                .and_then(|t| now.checked_duration_since(t))
                .is_none_or(|d| d < period)
        {
            return Ok(None);
        }
        let Some(source) = self.cached.take() else {
            return Ok(None);
        };
        let record = self.process_source(&source, true, Instant::now(), 0.0)?;
        self.cached = Some(source);
        self.last_output = Some(now);
        Ok(Some(record))
    }
    pub fn repeat_delay(&self, now: Instant) -> Option<Duration> {
        if self.cancelled() || self.cached.is_none() {
            return None;
        }
        super::cadence::remaining(
            self.last_output,
            Duration::from_secs_f64(1.0 / self.config.fps as f64),
            now,
        )
    }
    pub fn repeat_if_due(&mut self, now: Instant) -> Result<()> {
        if let Some(record) = self.repeat_record(now)? {
            emit(&record)?;
        }
        Ok(())
    }
    fn process_source(
        &mut self,
        source: &CachedSource,
        reused: bool,
        started: Instant,
        capture_ms: f64,
    ) -> Result<serde_json::Value> {
        let work_started_ns = super::monotonic_ns();
        let frame_started_ns = work_started_ns
            .checked_sub(started.elapsed().as_nanos().try_into()?)
            .context("Capture work clock overflow")?;
        let elapsed = self.temporal_clock.advance(frame_started_ns);
        if let Some(elapsed) = elapsed {
            self.pipeline.set_temporal_elapsed(elapsed);
            if let Some(shadow) = &mut self.shadow {
                shadow.set_temporal_elapsed(elapsed);
            }
        }
        if let Ok(sent) = self.sent.lock() {
            if !sent.is_empty() {
                self.pipeline.override_sent(&sent);
                if let Some(shadow) = &mut self.shadow {
                    shadow.override_sent(&sent);
                }
            }
        }
        let pixel_path = self.needs_pixels(source.width, source.height);
        let output = if pixel_path {
            self.pipeline.process(
                source
                    .pixels
                    .as_ref()
                    .context("Pixel policy has no capture pixels")?,
                &self.config,
            )?
        } else {
            self.pipeline.process_sdr_samples_with_bounds(
                source.width,
                source.height,
                &source.samples,
                &self.config,
                source.bounds,
            )?
        };
        let parity_exact = if let Some(shadow) = &mut self.shadow {
            if !pixel_path {
                let reference = shadow.process(
                    source
                        .pixels
                        .as_ref()
                        .context("Parity check has no reference pixels")?,
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
        let age = started.elapsed().as_secs_f64() * 1000.0;
        let backend = if pixel_path {
            "xdg-portal / Vulkan DMA-BUF / CPU pixel policies"
        } else {
            "xdg-portal / Vulkan DMA-BUF / direct SDR samples"
        };
        let backend = format!(
            "{backend} / {}{}",
            if std::env::var_os("NANOLEAF_EXPLICIT_SYNC").is_some() {
                "explicit sync"
            } else {
                "implicit sync"
            },
            if std::env::var_os("NANOLEAF_PRECISE_CACHE_TIMING").is_some() {
                " / precise cache timer"
            } else {
                ""
            }
        );
        Ok(
            serde_json::json!({"schema":3,"colors":output.colors,"unquantized_rgb":output.unquantized_rgb,
            "times":output.times,"capture_ms":capture_ms,"prepared_age_ms":age,"source_pts_ns":source.pts,
            "temporal_elapsed_ns":elapsed.map(|d| d.as_nanos() as u64),
            "source_reused":reused,"frame_started_ns":frame_started_ns,
            "backend":backend,"parity_exact":parity_exact,"highlight_cache":output.highlight_cache}),
        )
    }
}
fn emit(record: &serde_json::Value) -> Result<()> {
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    serde_json::to_writer(&mut stdout, record)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
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
        if std::env::var_os("NANOLEAF_EXPLICIT_SYNC").is_some() {
            super::Mode::DmaExplicit
        } else {
            super::Mode::Dma
        },
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

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn line_certificates_match_the_actual_pipeline_mean_contract() {
        // Cross-crate regression: changes to the production luma expression
        // must not silently invalidate the separately implemented bound.
        let mut accepted = 0;
        for length in [1, 7, 641, 3840, 16384] {
            for seed in 0..128_u32 {
                let mut bytes = Vec::with_capacity(length * 3);
                let mut totals = [0, 0, 0, length as u32];
                let mut state = seed + 1;
                for _ in 0..length {
                    for sum in &mut totals[..3] {
                        state = state.wrapping_mul(1664525).wrapping_add(1013904223);
                        let value = if seed.is_multiple_of(4) {
                            4
                        } else {
                            ((state >> 16) % 9) as u8
                        };
                        bytes.push(value);
                        *sum += u32::from(value);
                    }
                }
                if let Some(value) = nanoleaf_linux_gpu::border::certify_luma_above(
                    totals,
                    pipeline::CONTENT_THRESHOLD,
                ) {
                    assert_eq!(
                        value,
                        pipeline::encoded_mean(&bytes).unwrap() > pipeline::CONTENT_THRESHOLD
                    );
                    accepted += 1;
                }
            }
        }
        assert!(accepted > 250);
    }
    #[test]
    fn cache_timer_is_disarmed_without_a_valid_source_or_after_cancellation() {
        let mut app = app(false);
        let now = Instant::now();
        app.last_output = Some(now);
        assert_eq!(app.repeat_delay(now), None);
        app.cached = Some(source(
            &app,
            Frame {
                width: 32,
                height: 24,
                pixels: vec![0; 32 * 24 * 3],
            },
        ));
        let period = Duration::from_secs_f64(1.0 / app.config.fps as f64);
        assert_eq!(app.repeat_delay(now), Some(period));
        assert_eq!(app.repeat_delay(now + period), Some(Duration::ZERO));
        app.stop.store(true, Ordering::Release);
        assert_eq!(app.repeat_delay(now + period), None);
        app.stop.store(false, Ordering::Release);
        app.invalidate();
        assert_eq!(app.repeat_delay(now), None);
    }
    use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler};

    #[test]
    fn capture_and_cached_work_share_one_non_reversing_clock() {
        let mut clock = TemporalClock::default();
        assert_eq!(clock.advance(110), None);
        for (now, expected) in [
            (130, 20),
            (140, 10),
            (150, 10),
            (170, 20),
            (180, 10),
            (180, 0),
            (175, 0),
            (190, 10),
        ] {
            assert_eq!(clock.advance(now), Some(Duration::from_nanos(expected)));
        }
        // Work intervals partition elapsed time even if presentation metadata
        // holds, jumps, disappears or describes a future display presentation.
        let mut clock = TemporalClock::default();
        clock.advance(1_000);
        let elapsed: u128 = [1_010, 1_020, 1_030, 1_040]
            .into_iter()
            .map(|t| clock.advance(t).unwrap().as_nanos())
            .sum();
        assert_eq!(elapsed, 40);
    }

    #[test]
    fn fresh_work_keeps_exact_colours_with_old_or_future_presentation_metadata() {
        for offset in [-30_000_000_000, 30_000_000_000] {
            let mut app = app(false);
            app.config.smoothing = 1.0;
            app.config.zone_temporal_accumulation = false;
            let mut source = source(
                &app,
                Frame {
                    width: 32,
                    height: 24,
                    pixels: vec![128; 32 * 24 * 3],
                },
            );
            source.pts = Some(super::super::monotonic_ns() + offset);
            let start = Instant::now() - Duration::from_millis(5);
            let record = app.process_source(&source, false, start, 1.0).unwrap();
            let reference = Pipeline::default()
                .process(source.pixels.as_ref().unwrap(), &app.config)
                .unwrap();
            assert_eq!(
                record["colors"],
                serde_json::to_value(reference.colors).unwrap()
            );
            assert_eq!(
                record["unquantized_rgb"],
                serde_json::to_value(reference.unquantized_rgb).unwrap()
            );
            assert_eq!(record["schema"], 3);
            assert_eq!(record["source_pts_ns"], source.pts.unwrap());
            let age = super::super::monotonic_ns() - record["frame_started_ns"].as_i64().unwrap();
            assert!((5_000_000..1_000_000_000).contains(&age));
            assert!(record["prepared_age_ms"].as_f64().unwrap() >= 5.0);
        }
    }

    fn app(pixel_policy: bool) -> Application {
        let mut config = Config {
            device_zone_count: 4,
            letterbox_detection: false,
            zone_temporal_accumulation: true,
            blue_noise_dither: true,
            color_style: if pixel_policy {
                "ambient".into()
            } else {
                "reference".into()
            },
            ..Default::default()
        };
        config.calibration.corner_anchor_top_left = 0;
        config.calibration.corner_anchor_top_right = 1;
        config.calibration.corner_anchor_bottom_right = 2;
        config.calibration.corner_anchor_bottom_left = 3;
        if pixel_policy {
            config.privacy_zones.push(nanoleaf_native::config::Rect {
                x: 0.0,
                y: 0.0,
                w: 0.25,
                h: 0.25,
            });
        }
        Application {
            config,
            pipeline: Pipeline::default(),
            shadow: Some(Pipeline::default()),
            sent: Arc::new(Mutex::new(vec![])),
            stop: Arc::new(AtomicBool::new(false)),
            cached: None,
            last_output: None,
            temporal_clock: TemporalClock::default(),
        }
    }
    fn source(app: &Application, frame: Frame) -> CachedSource {
        let zones = app.zones(frame.width, frame.height).unwrap();
        let sampler = SdrSampler::default();
        let view =
            SdrRgb8Frame::new(&frame.pixels, frame.width, frame.height, frame.width * 3).unwrap();
        CachedSource {
            width: frame.width,
            height: frame.height,
            samples: zones
                .into_iter()
                .map(|z| sampler.sample_zone(&view, z))
                .collect(),
            pixels: Some(frame),
            bounds: None,
            pts: Some(super::super::monotonic_ns()),
        }
    }
    #[test]
    fn static_source_reprocessing_matches_identical_pixel_input_and_ack_history() {
        for pixels in [false, true] {
            let mut app = app(pixels);
            let mut reference = Pipeline::default();
            let frame = |rgb: [u8; 3]| Frame {
                width: 32,
                height: 24,
                pixels: std::iter::repeat_n(rgb, 32 * 24).flatten().collect(),
            };
            for rgb in [[255, 0, 0], [0, 255, 0]] {
                let source = source(&app, frame(rgb));
                let record = app
                    .process_source(&source, false, Instant::now(), 0.0)
                    .unwrap();
                if let Some(ns) = record["temporal_elapsed_ns"].as_u64() {
                    reference.set_temporal_elapsed(Duration::from_nanos(ns));
                }
                let expected = reference
                    .process(source.pixels.as_ref().unwrap(), &app.config)
                    .unwrap();
                assert_eq!(
                    record["colors"],
                    serde_json::to_value(&expected.colors).unwrap()
                );
                assert_eq!(record["source_reused"], false);
                *app.sent.lock().unwrap() = expected.colors.clone();
                reference.override_sent(&expected.colors);
                app.cached = Some(source);
                app.last_output = Some(Instant::now());
            }
            let period = Duration::from_secs_f64(1.0 / app.config.fps as f64);
            let mut now = app.last_output.unwrap();
            assert!(app.repeat_record(now + period / 2).unwrap().is_none());
            for ack in 0..40 {
                now += period;
                let record = app.repeat_record(now).unwrap().unwrap();
                if let Some(ns) = record["temporal_elapsed_ns"].as_u64() {
                    reference.set_temporal_elapsed(Duration::from_nanos(ns));
                }
                let expected = reference.process(&frame([0, 255, 0]), &app.config).unwrap();
                assert_eq!(
                    record["colors"],
                    serde_json::to_value(&expected.colors).unwrap(),
                    "pixel policy {pixels}, tick {ack}"
                );
                assert_eq!(
                    record["unquantized_rgb"],
                    serde_json::to_value(&expected.unquantized_rgb).unwrap()
                );
                assert_eq!(record["source_reused"], true);
                assert_eq!(record["capture_ms"], 0.0);
                assert_eq!(record["schema"], 3);
                let sent = pipeline::quantize_acknowledged(&expected.unquantized_rgb, ack);
                *app.sent.lock().unwrap() = sent.clone();
                reference.override_sent(&sent);
            }
            let black = source(&app, frame([0; 3]));
            let record = app
                .process_source(&black, false, Instant::now(), 0.0)
                .unwrap();
            assert_eq!(record["colors"], serde_json::json!(vec![[0_u8; 3]; 4]));
            app.invalidate();
            assert!(app.repeat_record(now + period).unwrap().is_none());
        }
    }

    #[test]
    fn no_cached_output_before_a_source_or_after_cancellation() {
        let mut app = app(false);
        assert!(app
            .repeat_record(Instant::now() + Duration::from_secs(10))
            .unwrap()
            .is_none());
        app.cached = Some(source(
            &app,
            Frame {
                width: 32,
                height: 24,
                pixels: vec![128; 32 * 24 * 3],
            },
        ));
        app.last_output = Some(Instant::now());
        app.stop.store(true, Ordering::Release);
        assert!(app
            .repeat_record(Instant::now() + Duration::from_secs(10))
            .unwrap()
            .is_none());
        app.invalidate();
        assert!(app.cached.is_none());
    }
}
