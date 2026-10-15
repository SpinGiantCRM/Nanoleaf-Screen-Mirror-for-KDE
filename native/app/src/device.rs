//! One NL82K1/NL82K2 HID handle, authoritative manual count, acknowledged writes.
use anyhow::{bail, ensure, Result};
use hidapi::{HidApi, HidDevice};
use nanoleaf_core::protocol::{self, ChannelOrder};
use std::time::{Duration, Instant};

pub struct Strip {
    handle: HidDevice,
    count: usize,
    order: ChannelOrder,
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
        transact(&self.handle, command, payload)
    }

    pub fn frame(&mut self, colors: &[[u8; 3]]) -> Result<()> {
        self.last_frame_transaction = None;
        let request = protocol::encode_zone_frame(colors, self.count, self.order)?;
        let (_, times) =
            transact_timed(&self.handle, protocol::CMD_SET_ZONE_COLORS, &request[3..])?;
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
        self.frame(&vec![[0; 3]; self.count])
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
    for report in reports(&protocol::encode_request(command, payload)?) {
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
            if let Some(payload) = matching_response(command, candidate)? {
                times.ack_wait_ms = started.elapsed().as_secs_f64() * 1000.0;
                times.total_ms = total.elapsed().as_secs_f64() * 1000.0;
                return Ok((payload, times));
            }
        }
        ensure!(direct.len() <= 65538, "Oversized HID response");
    }
    bail!("Strip acknowledgement timed out")
}

fn matching_response(command: u8, mut bytes: &[u8]) -> Result<Option<Vec<u8>>> {
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
            return Ok(Some(protocol::parse_response(command, bytes)?.to_vec()));
        }
        bytes = &bytes[length + 3..];
        skipped_tlv = true;
    }
    Ok(None)
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
