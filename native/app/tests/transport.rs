use anyhow::Result;
use nanoleaf_native::device::{transact, ReportIo};
use std::cell::RefCell;
use std::collections::VecDeque;
struct Fake {
    reads: RefCell<VecDeque<Vec<u8>>>,
    writes: RefCell<Vec<Vec<u8>>>,
    short: bool,
}
impl ReportIo for Fake {
    fn write(&self, report: &[u8]) -> Result<usize> {
        self.writes.borrow_mut().push(report.to_vec());
        Ok(if self.short {
            report.len() - 1
        } else {
            report.len()
        })
    }
    fn read_timeout(&self, buffer: &mut [u8], timeout: i32) -> Result<usize> {
        if timeout == 0 && self.writes.borrow().is_empty() {
            return Ok(0);
        }
        let Some(next) = self.reads.borrow_mut().pop_front() else {
            return Ok(0);
        };
        buffer[..next.len()].copy_from_slice(&next);
        Ok(next.len())
    }
}
fn fake(reads: Vec<Vec<u8>>, short: bool) -> Fake {
    Fake {
        reads: RefCell::new(reads.into()),
        writes: RefCell::new(vec![]),
        short,
    }
}
#[test]
fn fragmented_and_report_id_responses_are_acknowledged() {
    let direct = fake(vec![vec![0x83, 0], vec![2, 0, 48]], false);
    assert_eq!(transact(&direct, 3, &[]).unwrap(), [48]);
    let prefixed = fake(vec![vec![0, 0x83, 0], vec![0, 2, 0, 48]], false);
    assert_eq!(transact(&prefixed, 3, &[]).unwrap(), [48]);
}
#[test]
fn uncertain_short_write_is_never_blindly_retried() {
    use nanoleaf_native::device::transact_timed_with_progress;
    let io = fake(vec![], true);
    assert!(transact_timed_with_progress(&io, 2, &[1; 144], || {
        panic!("Progress must not run inside a partial report write")
    })
    .is_err());
    assert_eq!(io.writes.borrow().len(), 1);
}
#[test]
fn firmware_failure_and_wrong_command_ack_are_not_successful_frames() {
    let failure = fake(vec![vec![0x82, 0, 1, 2]], false);
    assert!(transact(&failure, 2, &[1; 144]).is_err());
    let wrong = fake(vec![vec![0x83, 0, 1, 0]], false);
    assert!(transact(&wrong, 2, &[1; 144]).is_err());
    assert_eq!(wrong.writes.borrow().len(), 3);
}
#[test]
fn complete_late_unrelated_ack_cannot_hide_the_current_ack_or_fake_one_in_payload() {
    let late = fake(vec![vec![0x83, 0, 2, 0, 48], vec![0x82, 0, 1, 0]], false);
    assert_eq!(transact(&late, 2, &[1; 144]).unwrap(), Vec::<u8>::new());
    let inside = fake(vec![vec![0x83, 0, 5, 0, 0x82, 0, 1, 0]], false);
    assert!(transact(&inside, 2, &[1; 144]).is_err());
}

#[test]
fn transaction_stages_count_actual_reports_without_changing_wire_or_ack_matching() {
    use nanoleaf_native::device::transact_timed;
    let io = fake(vec![vec![0x83, 0, 2, 0, 48], vec![0x82, 0, 1, 0]], false);
    let (payload, times) = transact_timed(&io, 2, &[1; 144]).unwrap();
    assert!(payload.is_empty());
    assert_eq!(times.written_reports, 3);
    assert_eq!(times.report_write_ms.len(), 3);
    assert!(times
        .report_write_ms
        .iter()
        .all(|v| v.is_finite() && *v >= 0.0));
    assert!(times.write_completed.is_some());
    let json = serde_json::to_value(&times).unwrap();
    assert!(json.get("write_completed").is_none());
    assert_eq!(times.drained_reports, 0);
    assert_eq!(times.response_reports, 2);
    assert_eq!(
        io.writes.borrow().iter().map(Vec::len).collect::<Vec<_>>(),
        [65, 65, 20]
    );
    for ms in [
        times.drain_ms,
        times.write_ms,
        times.first_report_wait_ms,
        times.ack_wait_ms,
        times.total_ms,
    ] {
        assert!(ms.is_finite() && ms >= 0.0);
    }
    assert!(times.first_report_wait_ms <= times.ack_wait_ms);
    assert!(times.drain_ms + times.write_ms + times.ack_wait_ms <= times.total_ms);
}

#[test]
fn firmware_identity_byte_is_nibble_encoded_and_never_guessed_from_usb_bcd() {
    use nanoleaf_native::probe::decode_firmware_version;
    assert_eq!(decode_firmware_version(&[0x15]).unwrap(), (1, 5));
    assert_eq!(decode_firmware_version(&[0xaf]).unwrap(), (10, 15));
    assert!(decode_firmware_version(&[]).is_err());
    assert!(decode_firmware_version(&[1, 5]).is_err());
}

#[test]
fn stop_progress_releases_capture_while_retaining_serial_ack_ownership() {
    use nanoleaf_native::device::transact_timed_with_progress;
    use std::{cell::Cell, sync::mpsc};
    let (tx, rx) = mpsc::channel();
    let stopped = Cell::new(false);
    struct Delayed<'a> {
        writes: RefCell<Vec<Vec<u8>>>,
        reads: Cell<usize>,
        tx: mpsc::Sender<()>,
        stopped: &'a Cell<bool>,
    }
    impl ReportIo for Delayed<'_> {
        fn write(&self, report: &[u8]) -> Result<usize> {
            assert!(!self.stopped.get());
            self.writes.borrow_mut().push(report.to_vec());
            Ok(report.len())
        }
        fn read_timeout(&self, buffer: &mut [u8], timeout: i32) -> Result<usize> {
            if timeout == 0 && self.writes.borrow().is_empty() {
                return Ok(0);
            }
            assert!((0..=25).contains(&timeout));
            assert_eq!(self.writes.borrow().len(), 3);
            let n = self.reads.get();
            self.reads.set(n + 1);
            if n == 0 {
                // Stop arrives while the first bounded read is outstanding.
                self.tx.send(()).unwrap();
                Ok(0)
            } else {
                // Capture is already cancelled, but all reports remain owned
                // by this one transaction until the actual matching ACK.
                assert!(self.stopped.get());
                buffer[..4].copy_from_slice(&[0x82, 0, 1, 0]);
                Ok(4)
            }
        }
    }
    let io = Delayed {
        writes: RefCell::new(vec![]),
        reads: Cell::new(0),
        tx,
        stopped: &stopped,
    };
    let (body, times) = transact_timed_with_progress(&io, 2, &[17; 144], || {
        if rx.try_recv().is_ok() {
            stopped.set(true);
        }
    })
    .unwrap();
    assert!(body.is_empty());
    assert!(stopped.get());
    assert_eq!(times.written_reports, 3);
    assert_eq!(times.response_reports, 1);
    assert_eq!(io.reads.get(), 2);
}

#[test]
fn stop_progress_never_turns_a_missing_ack_into_a_success_or_new_write() {
    use nanoleaf_native::device::transact_timed_with_progress;
    let io = fake(vec![], false);
    let mut capture_cancelled = false;
    let error = transact_timed_with_progress(&io, 2, &[17; 144], || {
        capture_cancelled = true;
    })
    .unwrap_err();
    assert!(capture_cancelled);
    assert!(error.to_string().contains("acknowledgement timed out"));
    assert_eq!(io.writes.borrow().len(), 3);
}
