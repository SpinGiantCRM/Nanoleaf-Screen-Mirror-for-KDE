//! Scripted IO protects the experiment itself; the serial daily path is unchanged.
use anyhow::Result;
use nanoleaf_core::protocol::{encode_zone_frame, ChannelOrder};
use nanoleaf_native::device::{
    overlap::{pair, AckDecoder},
    ReportIo,
};
use std::{cell::RefCell, collections::VecDeque, time::Duration};
struct Io {
    writes: RefCell<Vec<Vec<u8>>>,
    reads: RefCell<VecDeque<Vec<u8>>>,
    writes_at_read: RefCell<Vec<usize>>,
    short_at: Option<usize>,
}
impl ReportIo for Io {
    fn write(&self, bytes: &[u8]) -> Result<usize> {
        let mut writes = self.writes.borrow_mut();
        writes.push(bytes.to_vec());
        Ok(if self.short_at == Some(writes.len()) {
            bytes.len() - 1
        } else {
            bytes.len()
        })
    }
    fn read_timeout(&self, buffer: &mut [u8], timeout: i32) -> Result<usize> {
        // No response ready in a zero-time readiness check. A blocking read
        // observes the next scripted reply; no assumption about an actual MCU.
        if timeout == 0 || self.writes.borrow().len() < 3 {
            return Ok(0);
        }
        let Some(bytes) = self.reads.borrow_mut().pop_front() else {
            return Ok(0);
        };
        buffer[..bytes.len()].copy_from_slice(&bytes);
        self.writes_at_read
            .borrow_mut()
            .push(self.writes.borrow().len());
        Ok(bytes.len())
    }
}
fn fake(reads: Vec<Vec<u8>>, short_at: Option<usize>) -> Io {
    Io {
        writes: RefCell::new(vec![]),
        reads: RefCell::new(reads.into()),
        writes_at_read: RefCell::new(vec![]),
        short_at,
    }
}
fn frames() -> [Vec<u8>; 2] {
    let order = ChannelOrder::parse("grb").unwrap();
    [[1, 2, 3], [4, 5, 6]].map(|rgb| encode_zone_frame(&[rgb; 48], 48, order).unwrap())
}
#[test]
fn serial_waits_for_first_reply_but_overlap_writes_both_exact_frames_first() {
    let frames = frames();
    for overlap in [false, true] {
        let io = fake(vec![vec![0x82, 0, 1, 0], vec![0x82, 0, 1, 0]], None);
        let result = pair(&io, [&frames[0], &frames[1]], overlap, Duration::ZERO).unwrap();
        assert_eq!(
            *io.writes_at_read.borrow(),
            if overlap { vec![6, 6] } else { vec![3, 6] }
        );
        assert_eq!(
            result.acks_observed_before_second_write,
            usize::from(!overlap)
        );
        assert_eq!(result.ack_observed_ms.len(), 2);
        let writes = io.writes.borrow();
        assert_eq!(
            writes.iter().map(Vec::len).collect::<Vec<_>>(),
            [65, 65, 20, 65, 65, 20]
        );
        for (i, frame) in frames.iter().enumerate() {
            assert_eq!(
                writes[i * 3..i * 3 + 3]
                    .iter()
                    .flat_map(|r| r[1..].iter().copied())
                    .collect::<Vec<_>>(),
                *frame
            );
        }
    }
}
#[test]
fn decoder_preserves_fragmented_prefixed_and_coalesced_acks_with_padding() {
    let mut d = AckDecoder::default();
    assert_eq!(d.feed(&[0, 0x82, 0], 2).unwrap(), 0);
    assert_eq!(d.feed(&[0, 1, 0, 0, 0, 0x82, 0, 1, 0, 0, 0], 2).unwrap(), 2);
    assert_eq!(d.count, 2);
    assert!(d.complete());
    let mut direct = AckDecoder::default();
    assert_eq!(direct.feed(&[0x82, 0, 1, 0, 0x82, 0, 1, 0], 2).unwrap(), 2);
}
#[test]
fn extra_or_unrelated_or_failed_or_payload_embedded_acks_fail_closed() {
    for bytes in [
        vec![0x82, 0, 1, 0, 0x82, 0, 1, 0],
        vec![0x83, 0, 1, 0],
        vec![0x82, 0, 1, 1],
        vec![0x83, 0, 5, 0, 0x82, 0, 1, 0],
        vec![0x82, 0, 2, 0, 0],
    ] {
        assert!(AckDecoder::default().feed(&bytes, 1).is_err());
    }
    let mut d = AckDecoder::default();
    assert_eq!(d.feed(&[0x82, 0, 1, 0, 0x82], 2).unwrap(), 1);
    assert!(!d.complete());
}
#[test]
fn uncertain_second_frame_short_write_is_never_retried() {
    let f = frames();
    let io = fake(vec![], Some(4));
    assert!(pair(&io, [&f[0], &f[1]], true, Duration::ZERO).is_err());
    assert_eq!(io.writes.borrow().len(), 4);
}
#[test]
fn missing_or_failed_second_ack_is_not_counted_as_a_successful_pair() {
    let f = frames();
    for replies in [
        vec![vec![0x82, 0, 1, 0]],
        vec![vec![0x82, 0, 1, 0], vec![0x82, 0, 1, 2]],
    ] {
        let io = fake(replies, None);
        assert!(pair(&io, [&f[0], &f[1]], true, Duration::ZERO).is_err());
        assert_eq!(io.writes.borrow().len(), 6);
    }
}
#[test]
fn geometry_and_complete_tlv_are_validated_before_any_write() {
    let f = frames();
    let io = fake(vec![], None);
    let mut malformed = f[1].clone();
    malformed.push(0);
    assert!(pair(&io, [&f[0], &malformed], true, Duration::ZERO).is_err());
    assert!(pair(&io, [&f[0], &f[1]], true, Duration::from_secs(1)).is_err());
    assert!(io.writes.borrow().is_empty());
}

#[test]
fn late_third_ack_fails_the_quiet_tail_instead_of_polluting_the_next_pair() {
    let f = frames();
    let io = fake(
        vec![
            vec![0x82, 0, 1, 0],
            vec![0x82, 0, 1, 0],
            vec![0x82, 0, 1, 0],
        ],
        None,
    );
    let error = pair(&io, [&f[0], &f[1]], true, Duration::ZERO).unwrap_err();
    assert!(error.to_string().contains("Unexpected extra reply"));
    assert_eq!(io.writes.borrow().len(), 6);
}
