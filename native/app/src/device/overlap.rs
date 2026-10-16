//! Operator-only two-frame experiment. Never used by the daily transport.
//! ACK order is only an assumption: the protocol carries no frame identifiers.
use super::{reports, ReportIo, Strip};
use crate::{config::Store, service};
use anyhow::{bail, ensure, Result};
use nanoleaf_core::protocol::{self, ChannelOrder};
use serde::Serialize;
use std::time::{Duration, Instant};

#[derive(Default)]
pub struct AckDecoder {
    prefixed: Option<bool>,
    bytes: Vec<u8>,
    pub count: usize,
}
impl AckDecoder {
    /// Complete TLVs only; never search a response body for ACK-looking bytes.
    pub fn feed(&mut self, report: &[u8], issued: usize) -> Result<usize> {
        ensure!(!report.is_empty(), "Empty report");
        let prefixed = *self.prefixed.get_or_insert(report[0] == 0);
        let bytes = if prefixed {
            ensure!(report[0] == 0, "Changed HID report prefix");
            &report[1..]
        } else {
            report
        };
        ensure!(
            self.bytes.len() + bytes.len() <= 2048,
            "Oversized overlap reply"
        );
        self.bytes.extend_from_slice(bytes);
        let before = self.count;
        loop {
            if self.bytes.is_empty() {
                break;
            }
            if self.bytes[0] == 0 {
                ensure!(self.count > 0, "Padding before any frame ACK");
                let padding = self.bytes.iter().take_while(|&&v| v == 0).count();
                self.bytes.drain(..padding);
                continue;
            }
            ensure!(
                self.bytes[0] == 0x82,
                "Unrelated response during frame window"
            );
            if self.bytes.len() < 3 {
                break;
            }
            ensure!(self.bytes[1..3] == [0, 1], "Unexpected frame ACK length");
            if self.bytes.len() < 4 {
                break;
            }
            protocol::parse_response(protocol::CMD_SET_ZONE_COLORS, &self.bytes[..4])?;
            ensure!(self.count < issued, "More ACKs than issued frames");
            self.count += 1;
            self.bytes.drain(..4);
        }
        Ok(self.count - before)
    }
    pub fn complete(&self) -> bool {
        self.bytes.is_empty()
    }
}

#[derive(Debug, Serialize)]
pub struct PairTimes {
    pub overlap_requested: bool,
    pub source_gap_ms: f64,
    pub write_started_ms: Vec<f64>,
    pub write_completed_ms: Vec<f64>,
    pub report_write_ms: Vec<Vec<f64>>,
    pub ack_observed_ms: Vec<f64>,
    pub acks_observed_before_second_write: usize,
    pub window_complete_ms: f64,
    pub quiet_check_ms: f64,
}
#[derive(Debug, Serialize)]
pub struct FailedPair {
    pub times: PairTimes,
    pub reason: String,
}
impl std::fmt::Display for FailedPair {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.reason)
    }
}
impl std::error::Error for FailedPair {}

fn receive(
    io: &impl ReportIo,
    decoder: &mut AckDecoder,
    issued: usize,
    wait: i32,
    epoch: Instant,
    times: &mut PairTimes,
) -> Result<()> {
    let mut raw = [0u8; 1024];
    let n = io.read_timeout(&mut raw, wait)?;
    if n > 0 {
        let observed = epoch.elapsed().as_secs_f64() * 1000.0;
        let count = decoder.feed(&raw[..n], issued)?;
        times
            .ack_observed_ms
            .extend(std::iter::repeat_n(observed, count));
    }
    Ok(())
}

/// Exactly two complete requests. No third request, retries or intermediate drain.
/// Event timestamps are when userspace observes IO, not optical/USB arrival times.
pub fn pair(
    io: &impl ReportIo,
    frames: [&[u8]; 2],
    overlap: bool,
    gap: Duration,
) -> Result<PairTimes> {
    measured_pair(io, frames, overlap, gap, true)
}
fn measured_pair(
    io: &impl ReportIo,
    frames: [&[u8]; 2],
    overlap: bool,
    gap: Duration,
    quiet_check: bool,
) -> Result<PairTimes> {
    ensure!(gap <= Duration::from_millis(40), "Unbounded source gap");
    for frame in frames {
        let (command, payload) = protocol::parse_tlv(frame)?;
        ensure!(
            command == protocol::CMD_SET_ZONE_COLORS
                && !payload.is_empty()
                && payload.len() <= 512 * 3
                && payload.len().is_multiple_of(3)
                && frame.len() == payload.len() + 3,
            "Invalid complete frame request"
        );
    }
    ensure!(
        frames[0].len() == frames[1].len(),
        "Manual count changed inside pair"
    );
    let mut raw = [0u8; 1024];
    ensure!(
        io.read_timeout(&mut raw, 0)? == 0,
        "Stale report before pair; resynchronize first"
    );
    let epoch = Instant::now();
    let deadline = epoch + Duration::from_millis(250);
    let mut times = PairTimes {
        overlap_requested: overlap,
        source_gap_ms: gap.as_secs_f64() * 1000.0,
        write_started_ms: vec![],
        write_completed_ms: vec![],
        report_write_ms: vec![],
        ack_observed_ms: vec![],
        acks_observed_before_second_write: 0,
        window_complete_ms: 0.0,
        quiet_check_ms: 0.0,
    };
    let mut decoder = AckDecoder::default();
    let measured = (|| -> Result<()> {
        for (i, frame) in frames.into_iter().enumerate() {
            ensure!(
                Instant::now() < deadline,
                "Frame window timed out before request"
            );
            if i == 1 {
                while Instant::now() < epoch + gap || (!overlap && decoder.count < 1) {
                    ensure!(
                        Instant::now() < deadline,
                        "First ACK/source deadline timed out"
                    );
                    let due = if !overlap && decoder.count < 1 {
                        deadline
                    } else {
                        epoch + gap
                    };
                    let left = due
                        .saturating_duration_since(Instant::now())
                        .as_millis()
                        .clamp(1, 5) as i32;
                    receive(io, &mut decoder, 1, left, epoch, &mut times)?;
                }
                // Observe any ready ACK before classifying the second write as overlap.
                receive(io, &mut decoder, 1, 0, epoch, &mut times)?;
                times.acks_observed_before_second_write = decoder.count;
            }
            times
                .write_started_ms
                .push(epoch.elapsed().as_secs_f64() * 1000.0);
            let mut writes = Vec::new();
            for report in reports(frame) {
                let started = Instant::now();
                ensure!(
                    io.write(&report)? == report.len(),
                    "Short overlap report write; no retry"
                );
                writes.push(started.elapsed().as_secs_f64() * 1000.0);
            }
            times
                .write_completed_ms
                .push(epoch.elapsed().as_secs_f64() * 1000.0);
            times.report_write_ms.push(writes);
        }
        while decoder.count < 2 {
            ensure!(Instant::now() < deadline, "Missing ACK in two-frame window");
            receive(io, &mut decoder, 2, 5, epoch, &mut times)?;
        }
        ensure!(decoder.complete(), "Trailing partial reply after window");
        times.window_complete_ms = epoch.elapsed().as_secs_f64() * 1000.0;
        // A quiet tail detects unexpected extra/delayed replies before the next case.
        // It is excluded from the window timing; any report is a failed experiment.
        if quiet_check {
            let quiet = Instant::now();
            ensure!(
                io.read_timeout(&mut raw, 30)? == 0,
                "Unexpected extra reply after two ACKs"
            );
            times.quiet_check_ms = quiet.elapsed().as_secs_f64() * 1000.0;
        }
        Ok(())
    })();
    if let Err(error) = measured {
        return Err(FailedPair {
            times,
            reason: error.to_string(),
        }
        .into());
    }
    Ok(times)
}

pub fn probe(store: &Store, gap_ms: Option<f64>, train: bool) -> Result<()> {
    if let Some(gap) = gap_ms {
        ensure!(
            gap.is_finite() && (0.0..=40.0).contains(&gap),
            "Source gap must be 0 to 40 ms"
        );
    }
    let _owner = service::acquire_output(&service::Paths::new()?)?;
    let c = &store.config;
    let mut strip = Strip::open(
        c.device_vid,
        c.device_pid,
        c.device_zone_count,
        &c.output_channel_order,
    )?;
    let power = strip.request(0x06, &[])?;
    let brightness = strip.request(0x08, &[])?;
    ensure!(
        power.len() == 1 && power[0] <= 1 && brightness.len() == 1,
        "Invalid original controller state"
    );
    let mut cases = Vec::new();
    let mut initial_test_brightness = None;
    let result = (|| -> Result<()> {
        strip.request(0x09, &[10])?;
        strip.request(0x07, &[1])?;
        initial_test_brightness = Some(strip.request(0x08, &[])?);
        let order = ChannelOrder::parse(&c.output_channel_order)?;
        let encode = |rgb| {
            protocol::encode_zone_frame(&vec![rgb; c.device_zone_count], c.device_zone_count, order)
        };
        // Low-brightness, neutral patterns; same report bytes in A/B modes.
        for (pattern, first, second) in [
            ("constant-grey-64", [64; 3], [64; 3]),
            ("grey-64-to-black", [64; 3], [0; 3]),
            ("constant-grey", [8; 3], [8; 3]),
            ("grey-to-black", [8; 3], [0; 3]),
            ("black-to-grey", [0; 3], [8; 3]),
        ] {
            let frames = [encode(first)?, encode(second)?];
            for gap in gap_ms
                .map(|gap| vec![gap])
                .unwrap_or_else(|| vec![0.0, 8.0, 16.666667])
            {
                for overlap in [false, true, true, false] {
                    std::thread::sleep(Duration::from_millis(40));
                    let mut samples = Vec::new();
                    for _ in 0..if train { 32 } else { 8 } {
                        // Start without unresolved frames; never a third outstanding request.
                        match measured_pair(
                            &strip.handle,
                            [&frames[0], &frames[1]],
                            overlap,
                            Duration::from_secs_f64(gap / 1000.0),
                            !train,
                        ) {
                            Ok(times) => samples.push(times),
                            Err(error) => {
                                cases.push(serde_json::json!({"pattern":pattern,"overlap":overlap,"target_source_gap_ms":gap,"samples":samples,"failed_window":error.downcast_ref::<FailedPair>(),"error":error.to_string()}));
                                return Err(error);
                            }
                        }
                    }
                    // End-of-case quiet check also applies to trains, where
                    // pairs followed each other immediately after both ACKs.
                    let mut raw = [0u8; 1024];
                    ensure!(
                        strip.handle.read_timeout(&mut raw, 30)? == 0,
                        "Unexpected late reply at case barrier"
                    );
                    // Distinct command barrier after every case, not per frame.
                    let after_brightness = strip.request(0x08, &[])?;
                    ensure!(
                        after_brightness.len() == 1,
                        "Invalid post-window controller reply"
                    );
                    cases.push(serde_json::json!({"pattern":pattern,"overlap":overlap,"target_source_gap_ms":gap,"samples":samples,"brightness_after_frames":after_brightness}));
                }
            }
        }
        Ok(())
    })();
    // Never retry an uncertain overlap. Quiesce, then independently verify
    // ordinary command replies before restoring through the serial reference.
    let mut raw = [0u8; 1024];
    let quiesce = Instant::now();
    let mut quiet = false;
    while quiesce.elapsed() < Duration::from_secs(1) {
        match strip.handle.read_timeout(&mut raw, 100) {
            Ok(0) => {
                quiet = true;
                break;
            }
            Ok(_) => {}
            Err(_) => break,
        }
    }
    let barrier = strip.request(0x08, &[]).is_ok();
    let black = strip.black().is_ok();
    let restored = strip.restore_controller(&power, &brightness);
    println!(
        "{}",
        serde_json::json!({"scope":"Operator-only generated neutral frames with saved manual zone count; two outstanding maximum; ordered ACK counting is an assumption, not frame identity; no capture or optical measurement","model":strip.model,"manual_zones":c.device_zone_count,"initial_test_brightness":initial_test_brightness,"train_without_inter_pair_quiet":train,"cases":cases,"error":result.as_ref().err().map(ToString::to_string),"quiescent_cleanup":quiet,"serial_barrier":barrier,"black_cleanup_acknowledged":black,"controller_power_brightness_restored":restored})
    );
    result?;
    if !(quiet && barrier && black && restored) {
        bail!("Overlap cleanup/restoration not verified");
    }
    Ok(())
}
