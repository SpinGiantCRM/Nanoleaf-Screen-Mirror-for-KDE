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
                    };
                    let bytes = strip.request(0x0c, &[])?;
                    strip.model = protocol::parse_model(&bytes)?.to_string();
                    let length = strip.request(0x03, &[])?;
                    ensure!(length.len() == 2, "Invalid device length reply");
                    strip.reported_count = u16::from_be_bytes([length[0], length[1]]) as usize;
                    // reported_count is diagnostics only, never runtime geometry.
                    return Ok(strip);
                }
                Err(error) => errors.push(error.to_string()),
            }
        }
        bail!("Unable to open the configured strip: {}", errors.join("; "))
    }

    pub fn request(&mut self, command: u8, payload: &[u8]) -> Result<Vec<u8>> {
        // Drain old reports before a new acknowledged transaction.
        let mut raw = [0_u8; 1024];
        for _ in 0..16 {
            if self.handle.read_timeout(&mut raw, 0)? == 0 {
                break;
            }
        }
        for report in reports(&protocol::encode_request(command, payload)?) {
            ensure!(
                self.handle.write(&report)? == report.len(),
                "Short HID report write"
            );
        }
        let started = Instant::now();
        let timeout = Duration::from_millis(250);
        let mut direct = vec![];
        let mut prefixed = vec![];
        while started.elapsed() < timeout {
            let Some(remaining) = timeout.checked_sub(started.elapsed()) else {
                break;
            };
            let left = remaining.as_millis().min(25) as i32;
            let size = self.handle.read_timeout(&mut raw, left)?;
            if size == 0 {
                continue;
            }
            direct.extend_from_slice(&raw[..size]);
            if size > 1 {
                prefixed.extend_from_slice(&raw[1..size]);
            }
            for candidate in [&direct, &prefixed] {
                if candidate.len() >= 3 && candidate[0] == command.wrapping_add(0x80) {
                    let length = u16::from_be_bytes([candidate[1], candidate[2]]) as usize;
                    if candidate.len() >= length + 3 {
                        return Ok(protocol::parse_response(command, candidate)?.to_vec());
                    }
                }
            }
            ensure!(direct.len() <= 65538, "Oversized HID response");
        }
        bail!("Strip acknowledgement timed out")
    }

    pub fn frame(&mut self, colors: &[[u8; 3]]) -> Result<()> {
        let request = protocol::encode_zone_frame(colors, self.count, self.order)?;
        self.request(protocol::CMD_SET_ZONE_COLORS, &request[3..])?;
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
}

pub fn reports(request: &[u8]) -> Vec<[u8; 65]> {
    request
        .chunks(64)
        .map(|chunk| {
            let mut report = [0; 65];
            report[1..1 + chunk.len()].copy_from_slice(chunk);
            report
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_tlv_bytes_survive_report_padding_and_ids() {
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
        assert_eq!(&joined[..tlv.len()], &tlv);
        assert!(joined[tlv.len()..].iter().all(|&byte| byte == 0));
    }
}
