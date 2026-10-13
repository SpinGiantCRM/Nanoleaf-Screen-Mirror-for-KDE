use nanoleaf_core::adaptive::MixedDecision;
use nanoleaf_core::sampling::{SdrRgb8Frame, SdrSampler, ZoneRect};

fn rect(width: i64, height: i64) -> ZoneRect {
    ZoneRect {
        x: 0,
        y: 0,
        width,
        height,
    }
}

#[test]
fn every_uniform_neutral_is_clear() {
    let sampler = SdrSampler::default();
    for code in 0..=255 {
        let bytes = [code; 48];
        let frame = SdrRgb8Frame::new(&bytes, 4, 4, 12).unwrap();
        assert_eq!(
            sampler.adaptive_prepass(&frame, rect(4, 4)).decision,
            MixedDecision::Clear
        );
    }
}

#[test]
fn neutral_checkerboard_is_mixed_with_linear_mean() {
    let mut bytes = vec![0; 48];
    bytes[24..].fill(255);
    let frame = SdrRgb8Frame::new(&bytes, 4, 4, 12).unwrap();
    let result = SdrSampler::default().adaptive_prepass(&frame, rect(4, 4));
    assert_eq!(result.decision, MixedDecision::Mixed);
    assert_eq!(result.mixed_rgb, [188; 3]);
}

#[test]
fn empty_clipped_and_negative_rectangles_are_safe() {
    let bytes = [128; 48];
    let frame = SdrRgb8Frame::new(&bytes, 4, 4, 12).unwrap();
    let sampler = SdrSampler::default();
    for zone in [
        rect(0, 0),
        rect(-1, 4),
        ZoneRect {
            x: i64::MAX,
            ..rect(4, 4)
        },
    ] {
        assert_eq!(
            sampler.adaptive_prepass(&frame, zone).decision,
            MixedDecision::Clear
        );
    }
}

#[test]
fn padded_rows_match_compact_rows() {
    let compact: Vec<_> = (0..99).map(|i| (i * 31) as u8).collect();
    let mut padded = Vec::new();
    for row in compact.chunks_exact(33) {
        padded.extend_from_slice(row);
        padded.extend([99; 7]);
    }
    let a = SdrRgb8Frame::new(&compact, 11, 3, 33).unwrap();
    let b = SdrRgb8Frame::new(&padded, 11, 3, 40).unwrap();
    let sampler = SdrSampler::default();
    let (a, b) = (
        sampler.adaptive_prepass(&a, rect(11, 3)),
        sampler.adaptive_prepass(&b, rect(11, 3)),
    );
    assert_eq!(a.decision, b.decision);
    assert_eq!(a.mixed_rgb, b.mixed_rgb);
}

#[test]
fn scratch_budget_exhaustion_requests_reference() {
    let bytes = vec![0; 1025 * 1024 * 3];
    let frame = SdrRgb8Frame::new(&bytes, 1025, 1024, 1025 * 3).unwrap();
    assert_eq!(
        SdrSampler::default()
            .adaptive_prepass(&frame, rect(1025, 1024))
            .decision,
        MixedDecision::Reference
    );
}
