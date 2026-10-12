use nanoleaf_native::capture::decode;

#[test]
fn rgb32_preserves_channels_padding_and_black() {
    let mut raw = Vec::new();
    raw.extend(u32::from_be_bytes([255, 10, 20, 30]).to_ne_bytes());
    raw.extend(u32::from_be_bytes([255, 128, 128, 128]).to_ne_bytes());
    raw.extend([99; 4]);
    raw.extend([0; 12]);
    let frame = decode(&raw, 2, 2, 12, 5).unwrap();
    assert_eq!(frame.pixels, [10, 20, 30, 128, 128, 128, 0, 0, 0, 0, 0, 0]);
}

#[test]
fn premultiplication_is_undone_and_zero_alpha_is_black() {
    let raw = [50, 25, 10, 128, 250, 250, 250, 0];
    assert_eq!(
        decode(&raw, 2, 1, 8, 18).unwrap().pixels,
        [100, 50, 20, 0, 0, 0]
    );
}

#[test]
fn undeclared_hdr_and_bad_geometry_fail_instead_of_reinterpreting_bytes() {
    assert!(decode(&[0; 8], 1, 1, 8, 35).is_err());
    assert!(decode(&[0; 3], 1, 1, 3, 5).is_err());
    assert!(decode(&[], 1, 1, 4, 5).is_err());
    assert!(decode(&[], 0, 0, 0, 5).is_err());
}
