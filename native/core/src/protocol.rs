//! Nanoleaf NL82K1/NL82K2 wire helpers. These functions never open USB devices.

use std::fmt;

pub const VENDOR_ID: u16 = 0x37fa;
pub const SUPPORTED_PRODUCT_IDS: [u16; 2] = [0x8201, 0x8202];
pub const SUPPORTED_MODELS: [&str; 2] = ["NL82K1", "NL82K2"];
pub const CMD_SET_ZONE_COLORS: u8 = 0x02;
pub const MAX_PAYLOAD: usize = u16::MAX as usize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Error {
    ShortRead,
    PayloadTooLarge,
    ResponseType,
    MissingStatus,
    CommandFailed(u8),
    InvalidChannelOrder,
    ZoneCountMismatch,
    UnsupportedModel,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::ShortRead => "short_read",
            Self::PayloadTooLarge => "payload_too_large",
            Self::ResponseType => "response_type",
            Self::MissingStatus => "missing_status",
            Self::CommandFailed(_) => "command_failed",
            Self::InvalidChannelOrder => "invalid_channel_order",
            Self::ZoneCountMismatch => "zone_count_mismatch",
            Self::UnsupportedModel => "unsupported_model",
        })
    }
}

impl std::error::Error for Error {}

pub fn supports_usb(vid: u16, pid: u16) -> bool {
    vid == VENDOR_ID && SUPPORTED_PRODUCT_IDS.contains(&pid)
}

pub fn parse_model(payload: &[u8]) -> Result<&str, Error> {
    let model = std::str::from_utf8(payload)
        .map_err(|_| Error::UnsupportedModel)?
        .trim_end_matches('\0')
        .trim();
    if SUPPORTED_MODELS.contains(&model) {
        Ok(model)
    } else {
        Err(Error::UnsupportedModel)
    }
}

pub fn encode_request(command: u8, payload: &[u8]) -> Result<Vec<u8>, Error> {
    let length = u16::try_from(payload.len()).map_err(|_| Error::PayloadTooLarge)?;
    let mut frame = Vec::with_capacity(3 + payload.len());
    frame.push(command);
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(payload);
    Ok(frame)
}

pub fn parse_tlv(data: &[u8]) -> Result<(u8, &[u8]), Error> {
    if data.len() < 3 {
        return Err(Error::ShortRead);
    }
    let length = usize::from(u16::from_be_bytes([data[1], data[2]]));
    let payload = data.get(3..3 + length).ok_or(Error::ShortRead)?;
    // Ignore trailing HID report padding, as in the Python reference.
    Ok((data[0], payload))
}

pub fn parse_response(command: u8, data: &[u8]) -> Result<&[u8], Error> {
    let (response_type, payload) = parse_tlv(data)?;
    if response_type != command.wrapping_add(0x80) {
        return Err(Error::ResponseType);
    }
    let (&status, body) = payload.split_first().ok_or(Error::MissingStatus)?;
    if status != 0 {
        return Err(Error::CommandFailed(status));
    }
    Ok(body)
}

#[derive(Debug, Clone, Copy)]
pub struct ChannelOrder([usize; 3]);

impl ChannelOrder {
    pub fn parse(order: &str) -> Result<Self, Error> {
        let indices = match order {
            "rgb" => [0, 1, 2],
            "rbg" => [0, 2, 1],
            "grb" => [1, 0, 2],
            "gbr" => [1, 2, 0],
            "brg" => [2, 0, 1],
            "bgr" => [2, 1, 0],
            _ => return Err(Error::InvalidChannelOrder),
        };
        Ok(Self(indices))
    }
}

pub fn encode_zone_frame(
    colors: &[[u8; 3]],
    manual_zone_count: usize,
    order: ChannelOrder,
) -> Result<Vec<u8>, Error> {
    if manual_zone_count == 0 || colors.len() != manual_zone_count {
        return Err(Error::ZoneCountMismatch);
    }
    let payload_len = colors.len().checked_mul(3).ok_or(Error::PayloadTooLarge)?;
    if payload_len > MAX_PAYLOAD {
        return Err(Error::PayloadTooLarge);
    }
    let mut payload = Vec::with_capacity(payload_len);
    for rgb in colors {
        for channel in order.0 {
            payload.push(rgb[channel]);
        }
    }
    encode_request(CMD_SET_ZONE_COLORS, &payload)
}
