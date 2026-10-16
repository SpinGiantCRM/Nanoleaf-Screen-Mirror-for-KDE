//! One NL82K1/NL82K2 HID handle, authoritative manual count, acknowledged writes.
mod ack_probe;
pub mod overlap;
mod updates;
use anyhow::{bail, ensure, Result};
use hidapi::{HidApi, HidDevice};
use nanoleaf_core::protocol::{self, ChannelOrder};
use std::time::{Duration, Instant};

pub struct Strip {
    handle: HidDevice,
    count: usize,
    order: ChannelOrder,
    updates: updates::Updates,
    pub model: String,
    pub reported_count: usize,
    pub last_frame_transaction: Option<TransactionTimes>,
}

/// Bounded timing metadata only; never retain HID payloads or screen colours.
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
pub struct TransactionTimes {
    pub drain_ms: f64,
    pub write_ms: f64,
    pub first_report_wait_ms: f64,
    pub ack_wait_ms: f64,
    pub total_ms: f64,
    pub drained_reports: u32,
    pub written_reports: u32,
    pub response_reports: u32,
    #[serde(default)]
    pub sent_zones: usize,
    #[serde(default)]
    pub unrelated_response: bool,
    #[serde(default)]
    pub report_write_ms: Vec<f64>,
    #[serde(skip)]
    pub write_completed: Option<Instant>,
}
impl Strip {
    pub fn open(vid: u16, pid: u16, manual_count: usize, order: &str) -> Result<Self> {
        ensure!(protocol::supports_usb(vid, pid), "Unsupported strip IDs");
        ensure!(
            (1..=512).contains(&manual_count),
            "Set a manual strip count between 1 and 512"
        );
        let api = HidApi::new()?;
        let mut candidates: Vec<_> = api
            .device_list()
            .filter(|d| d.vendor_id() == vid && d.product_id() == pid)
            .collect();
        candidates.sort_by_key(|d| {
            std::cmp::Reverse((d.usage_page() >= 0xff00, d.interface_number() == 0))
        });
        let mut errors = vec![];
        for device in candidates {
            match device.open_device(&api) {
                Ok(handle) => {
                    let mut strip = Self {
                        handle,
                        count: manual_count,
                        order: ChannelOrder::parse(order)?,
                        updates: updates::Updates::default(),
                        model: String::new(),
                        reported_count: 0,
                        last_frame_transaction: None,
                    };
                    let initialized = (|| -> Result<()> {
                        let bytes = strip.request(0x0c, &[])?;
                        strip.model = protocol::parse_model(&bytes)?.to_string();
                        let length = strip.request(0x03, &[])?;
                        strip.reported_count = protocol::parse_reported_count(&length)?;
                        Ok(())
                    })();
                    if let Err(error) = initialized {
                        errors.push(error.to_string());
                        continue;
                    }
                    // reported_count is diagnostics only, never runtime geometry.
                    return Ok(strip);
                }
                Err(error) => errors.push(error.to_string()),
            }
        }
        bail!("Unable to open the configured strip: {}", errors.join("; "))
    }

    pub fn request(&mut self, command: u8, payload: &[u8]) -> Result<Vec<u8>> {
        self.invalidate_updates();
        transact(&self.handle, command, payload)
    }

    /// Retention is verified only for this exact tested controller contract.
    /// Unknown identities/failed queries retain the complete-frame transport.
    pub fn enable_short_updates(&mut self) -> bool {
        self.updates.enabled = false;
        self.invalidate_updates();
        let model = self.model.clone();
        self.updates.enabled =
            updates::qualify(&model, self.count, |command| self.request(command, &[]));
        self.updates.enabled
    }

    pub fn invalidate_updates(&mut self) {
        self.updates.invalidate();
    }

    pub fn frame(&mut self, colors: &[[u8; 3]]) -> Result<()> {
        self.frame_with_progress(colors, || {})
    }
    /// Operator probe only. Never used by mirroring or calibration. A short
    /// command does not change this handle's authoritative full-frame count.
    pub(crate) fn probe_prefix(&mut self, colors: &[[u8; 3]]) -> Result<TransactionTimes> {
        self.invalidate_updates();
        let request = probe_prefix_request(colors, self.count, self.order)?;
        let (body, times) =
            transact_timed(&self.handle, protocol::CMD_SET_ZONE_COLORS, &request[3..])?;
        ensure!(body.is_empty(), "Unexpected prefix ACK body");
        Ok(times)
    }
    /// Service control can cancel capture between bounded ACK reads. It must
    /// never use this callback to start another transaction on this handle.
    pub fn frame_with_progress(
        &mut self,
        colors: &[[u8; 3]],
        progress: impl FnMut(),
    ) -> Result<()> {
        self.output_with_progress(colors, false, progress)
    }
    pub fn output_with_progress(
        &mut self,
        colors: &[[u8; 3]],
        shorten: bool,
        progress: impl FnMut(),
    ) -> Result<()> {
        self.last_frame_transaction = None;
        let times = self.updates.send(
            &self.handle,
            colors,
            self.count,
            self.order,
            shorten,
            progress,
        )?;
        self.last_frame_transaction = Some(times);
        Ok(())
    }
    pub fn on(&mut self) -> Result<()> {
        if self.request(0x06, &[])?.first() != Some(&1) {
            self.request(0x07, &[1])?;
        }
        if self
            .request(0x08, &[])?
            .first()
            .is_some_and(|value| *value < 10)
        {
            self.request(0x09, &[10])?;
        }
        Ok(())
    }
    pub fn black(&mut self) -> Result<()> {
        let result = self.frame(&vec![[0; 3]; self.count]);
        self.invalidate_updates();
        result
    }
    pub fn restore_controller(&mut self, power: &[u8], brightness: &[u8]) -> bool {
        // Attempt both restorations even when one fails, then verify readback.
        let b = self.request(0x09, brightness).is_ok();
        let p = self.request(0x07, power).is_ok();
        let verified_b = self.request(0x08, &[]).is_ok_and(|v| v == brightness);
        let verified_p = self.request(0x06, &[]).is_ok_and(|v| v == power);
        b && p && verified_b && verified_p
    }
}

fn probe_prefix_request(
    colors: &[[u8; 3]],
    manual_count: usize,
    order: ChannelOrder,
) -> Result<Vec<u8>> {
    ensure!(
        (8..=255).contains(&manual_count)
            && !colors.is_empty()
            && colors.len() < manual_count
            && colors.iter().flatten().all(|v| *v <= 64),
        "Operator prefix requires 1..manual_count zones, manual count 8..255, raw channels <=64"
    );
    Ok(protocol::encode_zone_frame(colors, colors.len(), order)?)
}

/// Injected report I/O for protocol failure/recovery tests; no raw USB in tests.
pub trait ReportIo {
    fn write(&self, report: &[u8]) -> Result<usize>;
    fn read_timeout(&self, buffer: &mut [u8], timeout_ms: i32) -> Result<usize>;
}
impl ReportIo for HidDevice {
    fn write(&self, report: &[u8]) -> Result<usize> {
        Ok(HidDevice::write(self, report)?)
    }
    fn read_timeout(&self, buffer: &mut [u8], timeout_ms: i32) -> Result<usize> {
        Ok(HidDevice::read_timeout(self, buffer, timeout_ms)?)
    }
}
pub fn transact(handle: &impl ReportIo, command: u8, payload: &[u8]) -> Result<Vec<u8>> {
    Ok(transact_timed(handle, command, payload)?.0)
}
pub fn transact_timed(
    handle: &impl ReportIo,
    command: u8,
    payload: &[u8],
) -> Result<(Vec<u8>, TransactionTimes)> {
    transact_timed_with_progress(handle, command, payload, || {})
}
/// Progress is serviced only after all report writes, between bounded reads.
/// ACK parsing, deadlines and serial transaction ownership remain unchanged.
pub fn transact_timed_with_progress(
    handle: &impl ReportIo,
    command: u8,
    payload: &[u8],
    progress: impl FnMut(),
) -> Result<(Vec<u8>, TransactionTimes)> {
    transact_packed(handle, command, payload, false, progress)
}

fn transact_packed(
    handle: &impl ReportIo,
    command: u8,
    payload: &[u8],
    single_transfer: bool,
    progress: impl FnMut(),
) -> Result<(Vec<u8>, TransactionTimes)> {
    transact_report_plan(
        handle,
        command,
        payload,
        |request| transfer_buffers(request, single_transfer),
        progress,
    )
}

fn transact_report_plan(
    handle: &impl ReportIo,
    command: u8,
    payload: &[u8],
    plan: impl FnOnce(&[u8]) -> Vec<Vec<u8>>,
    mut progress: impl FnMut(),
) -> Result<(Vec<u8>, TransactionTimes)> {
    let total = Instant::now();
    let mut times = TransactionTimes::default();
    // Drain old reports before a new acknowledged transaction.
    let mut raw = [0_u8; 1024];
    for _ in 0..16 {
        if handle.read_timeout(&mut raw, 0)? == 0 {
            break;
        }
        times.drained_reports += 1;
    }
    times.drain_ms = total.elapsed().as_secs_f64() * 1000.0;
    let write_start = Instant::now();
    let request = protocol::encode_request(command, payload)?;
    for report in plan(&request) {
        let report_start = Instant::now();
        ensure!(
            handle.write(&report)? == report.len(),
            "Short HID report write"
        );
        times
            .report_write_ms
            .push(report_start.elapsed().as_secs_f64() * 1000.0);
        times.written_reports += 1;
    }
    times.write_completed = Some(Instant::now());
    times.write_ms = write_start.elapsed().as_secs_f64() * 1000.0;
    let started = Instant::now();
    let timeout = Duration::from_millis(250);
    let mut direct = vec![];
    let mut prefixed = vec![];
    while started.elapsed() < timeout {
        progress();
        let Some(remaining) = timeout.checked_sub(started.elapsed()) else {
            break;
        };
        let left = remaining.as_millis().min(25) as i32;
        let size = handle.read_timeout(&mut raw, left)?;
        if size == 0 {
            continue;
        }
        if times.response_reports == 0 {
            times.first_report_wait_ms = started.elapsed().as_secs_f64() * 1000.0;
        }
        times.response_reports += 1;
        direct.extend_from_slice(&raw[..size]);
        if size > 1 {
            prefixed.extend_from_slice(&raw[1..size]);
        }
        for candidate in [&direct, &prefixed] {
            let (payload, unrelated) = matching_response(command, candidate)?;
            times.unrelated_response |= unrelated;
            if let Some(payload) = payload {
                times.ack_wait_ms = started.elapsed().as_secs_f64() * 1000.0;
                times.total_ms = total.elapsed().as_secs_f64() * 1000.0;
                return Ok((payload, times));
            }
        }
        ensure!(direct.len() <= 65538, "Oversized HID response");
    }
    bail!("Strip acknowledgement timed out")
}

fn transfer_buffers(request: &[u8], single_transfer: bool) -> Vec<Vec<u8>> {
    if single_transfer {
        // Linux hidraw removes this single unnumbered report-ID byte. USB's
        // endpoint packet size still divides the unchanged TLV at 64 bytes.
        // This is an operator hypothesis, not a portable HID report guarantee.
        let mut buffer = Vec::with_capacity(request.len() + 1);
        buffer.push(0);
        buffer.extend_from_slice(request);
        vec![buffer]
    } else {
        reports(request)
    }
}

fn matching_response(command: u8, mut bytes: &[u8]) -> Result<(Option<Vec<u8>>, bool)> {
    // A late ACK for another command must not hide the current ACK behind it.
    // Skip whole, complete TLVs, never scan their payload for a matching byte.
    let mut skipped_tlv = false;
    while bytes.len() >= 3 {
        if bytes[0] == 0 {
            if !skipped_tlv {
                break;
            }
            bytes = &bytes[1..];
            continue;
        }
        if !(0x80..=0x8f).contains(&bytes[0]) {
            break;
        }
        let length = u16::from_be_bytes([bytes[1], bytes[2]]) as usize;
        if bytes.len() < length + 3 {
            break;
        }
        if bytes[0] == command.wrapping_add(0x80) {
            // A button/other event may share the report *after* the ACK too.
            // Zero HID padding is benign; any other tail invalidates retained
            // colour state without changing ordinary response matching.
            let trailing = bytes[3 + length..].iter().any(|v| *v != 0);
            return Ok((
                Some(protocol::parse_response(command, bytes)?.to_vec()),
                skipped_tlv || trailing,
            ));
        }
        bytes = &bytes[length + 3..];
        skipped_tlv = true;
    }
    Ok((None, skipped_tlv))
}

/// Keep the final report short, as the verified Python transport does. Padding
/// after the TLV is unnecessary; preserve the reference's exact report lengths.
pub fn reports(request: &[u8]) -> Vec<Vec<u8>> {
    request
        .chunks(64)
        .map(|chunk| {
            let mut report = Vec::with_capacity(chunk.len() + 1);
            report.push(0);
            report.extend_from_slice(chunk);
            report
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn single_transfer_requires_a_matching_success_ack_and_never_retries_short_writes() {
        use std::cell::{Cell, RefCell};
        struct Io {
            writes: RefCell<Vec<Vec<u8>>>,
            response: RefCell<Vec<u8>>,
            short: bool,
            reads: Cell<usize>,
        }
        impl ReportIo for Io {
            fn write(&self, report: &[u8]) -> Result<usize> {
                self.writes.borrow_mut().push(report.to_vec());
                Ok(report.len() - usize::from(self.short))
            }
            fn read_timeout(&self, buffer: &mut [u8], timeout: i32) -> Result<usize> {
                if timeout == 0 {
                    return Ok(0);
                }
                self.reads.set(self.reads.get() + 1);
                let response = self.response.take();
                buffer[..response.len()].copy_from_slice(&response);
                Ok(response.len())
            }
        }
        for (reply, short, success) in [
            (vec![0x82, 0, 1, 0], false, true),
            (vec![0x82, 0, 1, 1], false, false),
            (vec![0x82, 0, 1, 0], true, false),
        ] {
            let io = Io {
                writes: RefCell::new(vec![]),
                response: RefCell::new(reply),
                short,
                reads: Cell::new(0),
            };
            let result = transact_packed(&io, 2, &[17; 144], true, || {});
            assert_eq!(result.is_ok(), success);
            let writes = io.writes.borrow();
            assert_eq!(writes.len(), 1);
            assert_eq!(writes[0].len(), 148);
            assert_eq!(&writes[0][..4], &[0, 2, 0, 144]);
            assert_eq!(io.reads.get(), usize::from(!short));
        }
    }
    #[test]
    fn single_transfer_preserves_every_endpoint_packet_without_intermediate_ids() {
        for count in [1, 20, 21, 22, 42, 48, 64, 75, 512] {
            let colors: Vec<_> = (0..count).map(|i| [i as u8, 17, 53]).collect();
            let request =
                protocol::encode_zone_frame(&colors, count, ChannelOrder::parse("grb").unwrap())
                    .unwrap();
            let ordinary = reports(&request);
            let candidate = transfer_buffers(&request, true);
            assert_eq!(candidate.len(), 1);
            assert_eq!(candidate[0][0], 0);
            assert_eq!(candidate[0][1..], request);
            assert_eq!(
                candidate[0][1..].chunks(64).collect::<Vec<_>>(),
                ordinary.iter().map(|r| &r[1..]).collect::<Vec<_>>()
            );
            assert_eq!(transfer_buffers(&request, false), ordinary);
        }
    }
    #[test]
    fn operator_prefix_keeps_channel_order_and_cannot_relax_full_frame_validation() {
        let order = ChannelOrder::parse("grb").unwrap();
        let request = probe_prefix_request(&[[8, 24, 64]; 12], 48, order).unwrap();
        assert_eq!(&request[..3], &[2, 0, 36]);
        assert!(request[3..].chunks_exact(3).all(|v| v == [24, 8, 64]));
        assert!(protocol::encode_zone_frame(&[[8; 3]; 12], 48, order).is_err());
        for colors in [vec![], vec![[0; 3]; 48], vec![[65; 3]; 12]] {
            assert!(probe_prefix_request(&colors, 48, order).is_err());
        }
        assert!(probe_prefix_request(&[[0; 3]], 512, order).is_err());
    }
    #[test]
    fn exact_tlv_bytes_survive_report_ids_without_tail_padding() {
        let colors = vec![[10, 20, 30]; 48];
        let tlv =
            protocol::encode_zone_frame(&colors, 48, ChannelOrder::parse("grb").unwrap()).unwrap();
        let chunks = reports(&tlv);
        assert_eq!(chunks.len(), 3);
        assert!(chunks.iter().all(|chunk| chunk[0] == 0));
        let joined: Vec<_> = chunks
            .iter()
            .flat_map(|chunk| chunk[1..].iter().copied())
            .collect();
        assert_eq!(joined, tlv);
        assert_eq!(
            chunks.iter().map(Vec::len).collect::<Vec<_>>(),
            [65, 65, 20]
        );
    }
}
