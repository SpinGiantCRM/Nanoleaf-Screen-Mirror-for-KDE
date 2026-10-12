use nanoleaf_core::protocol::{self, ChannelOrder, Error as ProtocolError};
use nanoleaf_core::sampling::{
    Error as SampleError, SdrRgb8Frame, SdrSampler, ZoneRect, ZoneSample,
};

fn rect(width: i64, height: i64) -> ZoneRect {
    ZoneRect {
        x: 0,
        y: 0,
        width,
        height,
    }
}

#[test]
fn models_and_ids_stay_specific_to_supported_nanoleaf() {
    for (model, pid) in [("NL82K1", 0x8201), ("NL82K2", 0x8202)] {
        assert_eq!(protocol::parse_model(model.as_bytes()), Ok(model));
        assert!(protocol::supports_usb(0x37fa, pid));
    }
    assert!(!protocol::supports_usb(0x37fa, 0x8203));
    assert!(!protocol::supports_usb(0x1234, 0x8202));
    assert!(protocol::parse_model(b"OTHER!").is_err());
    assert!(protocol::parse_model(b"\xff").is_err());
    assert_eq!(protocol::parse_model(b" NL82K2\0"), Ok("NL82K2"));
}

#[test]
fn tlv_length_boundaries_and_padding() {
    for size in [0, 1, 255, 256, 65535] {
        let payload = vec![42; size];
        let request = protocol::encode_request(2, &payload).unwrap();
        assert_eq!(protocol::parse_tlv(&request), Ok((2, payload.as_slice())));
    }
    assert_eq!(
        protocol::encode_request(2, &vec![0; 65536]),
        Err(ProtocolError::PayloadTooLarge)
    );
    assert_eq!(
        protocol::parse_response(3, &[0x83, 0, 2, 0, 48, 0, 0]),
        Ok(&[48][..])
    );
    assert_eq!(
        protocol::parse_response(0xff, &[0x7f, 0, 1, 0]),
        Ok(&[][..])
    );
}

#[test]
fn malformed_and_failed_responses_are_distinct() {
    assert_eq!(protocol::parse_tlv(&[0x82]), Err(ProtocolError::ShortRead));
    assert_eq!(
        protocol::parse_tlv(&[0x82, 0, 2, 0]),
        Err(ProtocolError::ShortRead)
    );
    assert_eq!(
        protocol::parse_response(2, &[0x83, 0, 1, 0]),
        Err(ProtocolError::ResponseType)
    );
    assert_eq!(
        protocol::parse_response(2, &[0x82, 0, 0]),
        Err(ProtocolError::MissingStatus)
    );
    assert_eq!(
        protocol::parse_response(2, &[0x82, 0, 1, 7]),
        Err(ProtocolError::CommandFailed(7))
    );
}

#[test]
fn manual_count_and_channel_order_are_explicit() {
    let colors = [[10, 20, 30], [40, 50, 60]];
    assert_eq!(
        protocol::encode_zone_frame(&colors, 2, ChannelOrder::parse("grb").unwrap()).unwrap(),
        [2, 0, 6, 20, 10, 30, 50, 40, 60]
    );
    for order in ["rgb", "rbg", "grb", "gbr", "brg", "bgr"] {
        assert!(ChannelOrder::parse(order).is_ok());
    }
    assert!(ChannelOrder::parse("rrb").is_err());
    assert_eq!(
        protocol::encode_zone_frame(&colors, 48, ChannelOrder::parse("rgb").unwrap()),
        Err(ProtocolError::ZoneCountMismatch)
    );
    assert_eq!(
        protocol::encode_zone_frame(&[], 0, ChannelOrder::parse("rgb").unwrap()),
        Err(ProtocolError::ZoneCountMismatch)
    );
}

#[test]
fn all_uniform_neutrals_are_exact_and_black_is_valid() {
    let sampler = SdrSampler::default();
    for code in 0..=255 {
        let bytes = [code; 18];
        let frame = SdrRgb8Frame::new(&bytes, 3, 2, 9).unwrap();
        let sample = sampler.sample_zone(&frame, rect(3, 2));
        assert_eq!(sample.srgb, [code; 3]);
        assert_eq!(sample.encoded_variance, 0.0);
        assert_eq!(sample.pixel_count, 6);
    }
}

#[test]
fn mixed_black_white_uses_linear_light() {
    let bytes = [0, 0, 0, 255, 255, 255];
    let frame = SdrRgb8Frame::new(&bytes, 2, 1, 6).unwrap();
    let sample = SdrSampler::default().sample_zone(&frame, rect(2, 1));
    assert_eq!(sample.srgb, [188; 3]);
    assert_eq!(sample.linear_rgb, [0.5; 3]);
    assert_eq!(sample.encoded_variance, 16256.25);
}

#[test]
fn stride_padding_clipping_and_remainder_pixels() {
    let bytes = [0, 0, 0, 0, 0, 0, 99, 99, 0, 0, 0, 255, 255, 255];
    let frame = SdrRgb8Frame::new(&bytes, 2, 2, 8).unwrap();
    let sampler = SdrSampler::default();
    assert_eq!(sampler.sample_zone(&frame, rect(2, 2)).pixel_count, 4);
    assert_eq!(
        sampler
            .sample_zone(
                &frame,
                ZoneRect {
                    x: 1,
                    y: 1,
                    width: 99,
                    height: 99
                }
            )
            .srgb,
        [255; 3]
    );
    assert_eq!(
        sampler
            .sample_zone(
                &frame,
                ZoneRect {
                    x: -1,
                    y: -1,
                    width: 1,
                    height: 1
                }
            )
            .pixel_count,
        1
    );
    assert_eq!(sampler.sample_zone(&frame, rect(0, 2)).pixel_count, 0);
    assert_eq!(
        sampler
            .sample_zone(
                &frame,
                ZoneRect {
                    x: i64::MAX,
                    y: 0,
                    width: i64::MAX,
                    height: 2
                }
            )
            .pixel_count,
        0
    );
    assert_eq!(
        sampler
            .sample_zone(&frame, rect(i64::MAX, i64::MAX))
            .pixel_count,
        4
    );
}

#[test]
fn invalid_buffers_and_output_sizes_fail_without_panics() {
    assert!(matches!(
        SdrRgb8Frame::new(&[], 0, 1, 0),
        Err(SampleError::InvalidDimensions)
    ));
    assert!(matches!(
        SdrRgb8Frame::new(&[0; 6], 2, 1, 5),
        Err(SampleError::InvalidStride)
    ));
    assert!(matches!(
        SdrRgb8Frame::new(&[0; 5], 2, 1, 6),
        Err(SampleError::TruncatedFrame)
    ));
    assert!(SdrRgb8Frame::new(&[], usize::MAX, 2, usize::MAX).is_err());
    let frame = SdrRgb8Frame::new(&[0; 6], 2, 1, 6).unwrap();
    assert_eq!(
        SdrSampler::default().sample_into(&frame, &[rect(2, 1)], &mut []),
        Err(SampleError::OutputLength)
    );
    let mut output = [ZoneSample::default(); 1];
    SdrSampler::default()
        .sample_into(&frame, &[rect(2, 1)], &mut output)
        .unwrap();
    assert_eq!(output[0].srgb, [0; 3]);
}

#[test]
fn response_length_sweep_never_accepts_truncated_payloads() {
    for actual in 0..64 {
        for declared in 0..64_u16 {
            let mut bytes = vec![0x82];
            bytes.extend_from_slice(&declared.to_be_bytes());
            bytes.resize(3 + actual, 0);
            let result = protocol::parse_response(2, &bytes);
            if usize::from(declared) > actual {
                assert_eq!(result, Err(ProtocolError::ShortRead));
            } else if declared == 0 {
                assert_eq!(result, Err(ProtocolError::MissingStatus));
            } else {
                assert_eq!(result.unwrap().len(), usize::from(declared) - 1);
            }
        }
    }
}
