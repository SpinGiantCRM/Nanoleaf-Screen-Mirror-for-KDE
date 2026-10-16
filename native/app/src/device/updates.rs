//! Exact acknowledged output state. No phase skipping or approximate colours.
use super::{transact_timed_with_progress, ReportIo, TransactionTimes};
use anyhow::{ensure, Result};
use nanoleaf_core::protocol::{self, ChannelOrder};
use std::time::{Duration, Instant};

const FULL_REFRESH: Duration = Duration::from_millis(250);

#[derive(Default)]
pub(crate) struct Updates {
    pub enabled: bool,
    last: Vec<[u8; 3]>,
    full_at: Option<Instant>,
}

pub(crate) fn verified(model: &str, count: usize, firmware: &[u8], hardware: &[u8]) -> bool {
    model == "NL82K2" && count == 48 && firmware == [0x15] && hardware == b"11"
}

pub(crate) fn qualify(
    model: &str,
    count: usize,
    mut query: impl FnMut(u8) -> Result<Vec<u8>>,
) -> bool {
    if model != "NL82K2" || count != 48 {
        return false;
    }
    let Ok(firmware) = query(0x0a) else {
        return false;
    };
    // Do not issue the vendor hardware query to an unverified firmware family.
    if firmware != [0x15] {
        return false;
    }
    query(0x0b).is_ok_and(|hardware| verified(model, count, &firmware, &hardware))
}

impl Updates {
    pub fn invalidate(&mut self) {
        self.last.clear();
        self.full_at = None;
    }

    fn length(&self, colors: &[[u8; 3]], now: Instant) -> usize {
        if !self.enabled
            || self.last.len() != colors.len()
            || self
                .full_at
                .is_none_or(|at| now.saturating_duration_since(at) >= FULL_REFRESH)
        {
            return colors.len();
        }
        // Even an identical frame sends one real acknowledged zone: the dither
        // phase and all existing ACK feedback advance exactly once per update.
        self.last
            .iter()
            .zip(colors)
            .rposition(|(a, b)| a != b)
            .map_or(1, |i| i + 1)
    }

    pub fn send(
        &mut self,
        io: &impl ReportIo,
        colors: &[[u8; 3]],
        count: usize,
        order: ChannelOrder,
        shorten: bool,
        progress: impl FnMut(),
    ) -> Result<TransactionTimes> {
        // Full-count validation and channel order are always authoritative.
        let result = (|| -> Result<_> {
            let full = protocol::encode_zone_frame(colors, count, order)?;
            // Button/other traffic already waiting before selection invalidates
            // retention *before* choosing a short payload. Normal ACK I/O still
            // drains again for traffic arriving during selection.
            let mut drained = 0;
            if shorten && self.enabled {
                let mut raw = [0u8; 1024];
                for _ in 0..16 {
                    if io.read_timeout(&mut raw, 0)? == 0 {
                        break;
                    }
                    drained += 1;
                    self.invalidate();
                }
            }
            let zones = if shorten {
                self.length(colors, Instant::now())
            } else {
                count
            };
            let (body, mut times) = transact_timed_with_progress(
                io,
                protocol::CMD_SET_ZONE_COLORS,
                &full[3..3 + zones * 3],
                progress,
            )?;
            ensure!(
                !self.enabled || body.is_empty(),
                "Unexpected colour ACK body"
            );
            times.sent_zones = zones;
            times.drained_reports += drained;
            // Unexpected replies/drained traffic cannot establish retained state.
            if self.enabled
                && body.is_empty()
                && times.drained_reports == 0
                && times.response_reports == 1
                && !times.unrelated_response
            {
                self.last.clear();
                self.last.extend_from_slice(colors);
                if zones == count {
                    self.full_at = Some(Instant::now());
                }
            } else {
                self.invalidate();
            }
            Ok(times)
        })();
        if result.is_err() {
            self.invalidate();
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipeline::quantize_acknowledged;
    use std::cell::{Cell, RefCell};

    #[derive(Default)]
    struct Io {
        bytes: RefCell<Vec<u8>>,
        state: RefCell<Vec<u8>>,
        reply: Cell<bool>,
        fail: Cell<bool>,
        short_write: Cell<bool>,
        missing: Cell<bool>,
        event: Cell<bool>,
        mixed_event: Cell<bool>,
        trailing_event: Cell<bool>,
        malformed: Cell<bool>,
        sent: RefCell<Vec<usize>>,
    }
    impl ReportIo for Io {
        fn write(&self, report: &[u8]) -> Result<usize> {
            let mut bytes = self.bytes.borrow_mut();
            bytes.extend_from_slice(&report[1..]);
            if bytes.len() >= 3 {
                let length = usize::from(u16::from_be_bytes([bytes[1], bytes[2]]));
                if bytes.len() == length + 3 {
                    assert_eq!(bytes[0], 2);
                    assert!(length > 0 && length % 3 == 0);
                    self.state.borrow_mut()[..length].copy_from_slice(&bytes[3..]);
                    self.sent.borrow_mut().push(length / 3);
                    bytes.clear();
                    self.reply.set(true);
                }
            }
            Ok(report.len() - usize::from(self.short_write.get()))
        }
        fn read_timeout(&self, out: &mut [u8], _timeout: i32) -> Result<usize> {
            if self.event.replace(false) {
                out[..5].copy_from_slice(&[0x85, 0, 2, 1, 1]);
                return Ok(5);
            }
            if !self.reply.replace(false) || self.missing.get() {
                return Ok(0);
            }
            if self.mixed_event.replace(false) {
                out[..9].copy_from_slice(&[0x85, 0, 2, 1, 1, 0x82, 0, 1, 0]);
                return Ok(9);
            }
            if self.trailing_event.replace(false) {
                out[..9].copy_from_slice(&[0x82, 0, 1, 0, 0x85, 0, 2, 1, 1]);
                return Ok(9);
            }
            if self.malformed.replace(false) {
                out[..5].copy_from_slice(&[0x82, 0, 2, 0, 99]);
                return Ok(5);
            }
            out[..4].copy_from_slice(&[0x82, 0, 1, u8::from(self.fail.get())]);
            Ok(4)
        }
    }
    fn io() -> Io {
        Io {
            state: RefCell::new(vec![0; 144]),
            ..Default::default()
        }
    }
    #[test]
    fn identity_refresh_changes_and_resets_are_conservative() {
        assert!(verified("NL82K2", 48, &[0x15], b"11"));
        for (m, n, f, h) in [
            ("NL82K1", 48, 0x15, b"11"),
            ("NL82K2", 47, 0x15, b"11"),
            ("NL82K2", 48, 0x16, b"11"),
            ("NL82K2", 48, 0x15, b"12"),
        ] {
            assert!(!verified(m, n, &[f], h));
        }
        let now = Instant::now();
        let mut s = Updates {
            enabled: true,
            last: vec![[8; 3]; 48],
            full_at: Some(now),
        };
        let mut c = s.last.clone();
        c[11] = [24; 3];
        assert_eq!(s.length(&c, now), 12);
        c[47] = [9; 3];
        assert_eq!(s.length(&c, now), 48);
        assert_eq!(s.length(&s.last, now), 1);
        assert_eq!(s.length(&s.last, now + FULL_REFRESH), 48);
        s.invalidate();
        assert_eq!(s.length(&c, now), 48);
    }
    #[test]
    fn identity_gate_never_queries_hardware_on_unknown_firmware_and_bad_ack_invalidates() {
        for (model, count, fw, expected) in [
            ("NL82K1", 48, 0x15, vec![]),
            ("NL82K2", 47, 0x15, vec![]),
            ("NL82K2", 48, 0x14, vec![0x0a]),
            ("NL82K2", 48, 0x15, vec![0x0a, 0x0b]),
        ] {
            let mut seen = Vec::new();
            let supported = qualify(model, count, |command| {
                seen.push(command);
                Ok(if command == 0x0a {
                    vec![fw]
                } else {
                    b"11".to_vec()
                })
            });
            assert_eq!(supported, expected.len() == 2);
            assert_eq!(seen, expected);
        }
        assert!(!qualify("NL82K2", 48, |_| anyhow::bail!(
            "missing identity ACK"
        )));
        let io = io();
        let mut s = Updates {
            enabled: true,
            ..Default::default()
        };
        let c = vec![[16; 3]; 48];
        let order = ChannelOrder::parse("rgb").unwrap();
        s.send(&io, &c, 48, order, true, || {}).unwrap();
        io.malformed.set(true);
        assert!(s.send(&io, &c, 48, order, true, || {}).is_err());
        let t = s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert_eq!(t.sent_zones, 48);
        io.trailing_event.set(true);
        let t = s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert!(t.unrelated_response);
        let t = s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert_eq!(t.sent_zones, 48);
    }
    #[test]
    fn every_ack_reconstructs_exact_full_output_including_fractional_tail_dithering() {
        for order in ["rgb", "rbg", "grb", "gbr", "brg", "bgr"] {
            let io = io();
            let mut s = Updates {
                enabled: true,
                ..Default::default()
            };
            let order = ChannelOrder::parse(order).unwrap();
            let mut raw = vec![[32.0; 3]; 48];
            raw[47] = [32.25, 63.5, 128.75];
            for frame in 0..128 {
                raw[0] = [f32::from((frame % 64) as u8), 8.5, 16.25];
                raw[11] = [24.0, f32::from((frame % 32) as u8), 64.0];
                let c = quantize_acknowledged(&raw, frame);
                s.send(&io, &c, 48, order, true, || {}).unwrap();
                assert_eq!(
                    *io.state.borrow(),
                    protocol::encode_zone_frame(&c, 48, order).unwrap()[3..]
                );
            }
            assert_eq!(io.sent.borrow().len(), 128);
            assert!(io.sent.borrow().contains(&48));
            assert!(io.sent.borrow().iter().any(|n| *n < 48));
        }
    }
    #[test]
    fn failed_ack_and_bad_shape_never_commit_state_and_next_write_is_full() {
        let io = io();
        let mut s = Updates {
            enabled: true,
            ..Default::default()
        };
        let order = ChannelOrder::parse("rgb").unwrap();
        let c = vec![[16; 3]; 48];
        s.send(&io, &c, 48, order, true, || {}).unwrap();
        io.fail.set(true);
        assert!(s.send(&io, &c, 48, order, true, || {}).is_err());
        io.fail.set(false);
        s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert_eq!(*io.sent.borrow(), [48, 1, 48]);
        assert!(s.send(&io, &c[..12], 48, order, true, || {}).is_err());
        s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert_eq!(*io.sent.borrow().last().unwrap(), 48);
        s.send(&io, &c, 48, order, false, || {}).unwrap();
        assert_eq!(*io.sent.borrow().last().unwrap(), 48);
    }

    #[test]
    fn missing_ack_uncertain_write_and_unsolicited_events_force_full_recovery() {
        let order = ChannelOrder::parse("rgb").unwrap();
        let c = vec![[16; 3]; 48];
        for short in [false, true] {
            let io = io();
            let mut s = Updates {
                enabled: true,
                ..Default::default()
            };
            s.send(&io, &c, 48, order, true, || {}).unwrap();
            io.short_write.set(short);
            io.missing.set(!short);
            assert!(s.send(&io, &c, 48, order, true, || {}).is_err());
            io.short_write.set(false);
            io.missing.set(false);
            s.send(&io, &c, 48, order, true, || {}).unwrap();
            assert_eq!(*io.sent.borrow().last().unwrap(), 48);
        }
        let io = io();
        let mut s = Updates {
            enabled: true,
            ..Default::default()
        };
        s.send(&io, &c, 48, order, true, || {}).unwrap();
        io.event.set(true);
        let t = s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert_eq!(t.sent_zones, 48);
        assert_eq!(t.drained_reports, 1);
        s.send(&io, &c, 48, order, true, || {}).unwrap();
        io.mixed_event.set(true);
        let t = s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert!(t.unrelated_response);
        let t = s.send(&io, &c, 48, order, true, || {}).unwrap();
        assert_eq!(t.sent_zones, 48);
    }

    #[test]
    fn independent_reconstruction_covers_all_neutrals_and_changed_prefix_extents() {
        let io = io();
        let mut s = Updates {
            enabled: true,
            ..Default::default()
        };
        let order = ChannelOrder::parse("bgr").unwrap();
        let mut c = vec![[8; 3]; 48];
        for code in 0..=255 {
            for last in 0..48 {
                c[last] = [code, 255 - code, code / 2];
                s.send(&io, &c, 48, order, true, || {}).unwrap();
                assert_eq!(
                    *io.state.borrow(),
                    protocol::encode_zone_frame(&c, 48, order).unwrap()[3..]
                );
            }
        }
    }
}
