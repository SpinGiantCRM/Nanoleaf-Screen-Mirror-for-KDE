//! Operator-only ACK-path experiments; never selected by mirroring.
use super::*;

impl Strip {
    /// Operator-only single-command transfer experiment. No overlapping TLVs,
    /// retries, firmware operations or changes to the daily report packing.
    pub(crate) fn probe_transfer(
        &mut self,
        colors: &[[u8; 3]],
        single_transfer: bool,
        output_ioctl: bool,
    ) -> Result<TransactionTimes> {
        self.invalidate_updates();
        ensure!(
            self.model == "NL82K2" && self.count == 48 && colors.iter().flatten().all(|v| *v <= 64),
            "Transfer probe requires the tested 48-zone NL82K2 and channels <=64"
        );
        let request = protocol::encode_zone_frame(colors, self.count, self.order)?;
        let (body, mut times) = if output_ioctl {
            ensure!(!single_transfer, "Do not combine transfer experiments");
            transact_timed(
                &OutputIo(&self.handle),
                protocol::CMD_SET_ZONE_COLORS,
                &request[3..],
            )?
        } else {
            transact_packed(
                &self.handle,
                protocol::CMD_SET_ZONE_COLORS,
                &request[3..],
                single_transfer,
                || {},
            )?
        };
        ensure!(body.is_empty(), "Unexpected transfer ACK body");
        times.sent_zones = self.count;
        Ok(times)
    }

    /// Read-only HID GET_REPORT experiment. No command is outstanding here;
    /// its contents must never be treated as a fresh colour acknowledgement.
    pub(crate) fn probe_control_read(&mut self) -> serde_json::Value {
        self.invalidate_updates();
        control_read(&self.handle)
    }

    pub(crate) fn probe_control_ack(&mut self, colors: &[[u8; 3]]) -> Result<serde_json::Value> {
        self.invalidate_updates();
        ensure!(
            self.model == "NL82K2" && self.count == 48 && colors.iter().flatten().all(|v| *v <= 64),
            "Untested control ACK probe frame"
        );
        let request = protocol::encode_zone_frame(colors, self.count, self.order)?;
        let mut control = None;
        let result = transact_timed_with_progress(
            &self.handle,
            protocol::CMD_SET_ZONE_COLORS,
            &request[3..],
            || {
                if control.is_none() {
                    control = Some(control_read(&self.handle));
                }
            },
        );
        let result = result.and_then(|(body, times)| {
            ensure!(body.is_empty(), "Unexpected colour ACK body");
            Ok(times)
        });
        Ok(
            serde_json::json!({"control_read":control,"ordinary_ack":result.as_ref().ok(),
            "error":result.as_ref().err().map(ToString::to_string)}),
        )
    }

    pub(crate) fn probe_pacing(
        &mut self,
        colors: &[[u8; 3]],
        gap_us: u64,
    ) -> Result<TransactionTimes> {
        self.invalidate_updates();
        ensure!(
            self.model == "NL82K2"
                && self.count == 48
                && gap_us <= 2000
                && colors.iter().flatten().all(|v| *v <= 64),
            "Untested pacing probe"
        );
        let request = protocol::encode_zone_frame(colors, self.count, self.order)?;
        let io = PacedIo {
            handle: &self.handle,
            gap: Duration::from_micros(gap_us),
            first: std::cell::Cell::new(true),
        };
        let (body, mut times) = transact_timed(&io, protocol::CMD_SET_ZONE_COLORS, &request[3..])?;
        ensure!(body.is_empty(), "Unexpected pacing ACK body");
        times.sent_zones = self.count;
        Ok(times)
    }
}

struct PacedIo<'a> {
    handle: &'a HidDevice,
    gap: Duration,
    first: std::cell::Cell<bool>,
}
impl ReportIo for PacedIo<'_> {
    fn write(&self, report: &[u8]) -> Result<usize> {
        if !self.first.replace(false) && !self.gap.is_zero() {
            std::thread::sleep(self.gap);
        }
        Ok(self.handle.write(report)?)
    }
    fn read_timeout(&self, buffer: &mut [u8], timeout_ms: i32) -> Result<usize> {
        Ok(self.handle.read_timeout(buffer, timeout_ms)?)
    }
}

/// Exercise the library's HIDIOCSOUTPUT path without changing report contents.
/// Some Linux implementations route this like write(); measure rather than
/// assuming the portable HID API's documented control-endpoint guarantee.
struct OutputIo<'a>(&'a HidDevice);
impl ReportIo for OutputIo<'_> {
    fn write(&self, report: &[u8]) -> Result<usize> {
        self.0.send_output_report(report)?;
        Ok(report.len())
    }
    fn read_timeout(&self, buffer: &mut [u8], timeout_ms: i32) -> Result<usize> {
        Ok(self.0.read_timeout(buffer, timeout_ms)?)
    }
}

fn control_read(handle: &HidDevice) -> serde_json::Value {
    let mut raw = [0u8; 65];
    let start = Instant::now();
    let result = handle.get_input_report(&mut raw);
    serde_json::json!({
        "elapsed_ms": start.elapsed().as_secs_f64()*1000.0,
        "returned_bytes": result.as_ref().ok(),
        "error": result.as_ref().err().map(ToString::to_string),
        "nonzero_data_bytes":result.as_ref().ok().map(|n| raw[..*n].iter().filter(|v| **v != 0).count()),
        "used_as_ack":false,
    })
}
