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
    let io = fake(vec![], true);
    assert!(transact(&io, 2, &[1; 144]).is_err());
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
