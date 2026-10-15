//! Offline container inspection only. No USB, network, decryption or flashing.
use anyhow::{ensure, Context, Result};
use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::PathBuf};

const RECORD_BYTES: usize = 61;
const MAX_BYTES: usize = 2 * 1024 * 1024;

fn inspect(bytes: &[u8], expected_sha256: &str) -> Result<serde_json::Value> {
    ensure!(
        expected_sha256.len() == 64 && expected_sha256.bytes().all(|b| b.is_ascii_hexdigit()),
        "Expected SHA-256 must contain exactly 64 hexadecimal characters"
    );
    ensure!(
        !bytes.is_empty() && bytes.len() <= MAX_BYTES,
        "Image must contain 1 byte to 2 MiB"
    );
    ensure!(
        bytes.len().is_multiple_of(RECORD_BYTES),
        "Truncated record or trailing data: expected complete 61-byte records"
    );
    let sha256 = format!("{:x}", Sha256::digest(bytes));
    ensure!(
        sha256.eq_ignore_ascii_case(expected_sha256),
        "Image SHA-256 differs from the independently recorded expected hash"
    );
    let version = bytes[0];
    let mut histogram = [0usize; 256];
    for (index, record) in bytes.chunks_exact(RECORD_BYTES).enumerate() {
        ensure!(
            record[0] == version,
            "Mixed firmware versions at record {index}"
        );
        ensure!(
            usize::from(u16::from_be_bytes([record[1], record[2]])) == index,
            "Missing, duplicated or unordered block at record {index}"
        );
        // The historical spec assigns bytes 3..59 to firmware data. The two
        // remaining bytes are opaque: their checksum/encoding is NOT verified.
        for byte in &record[3..59] {
            histogram[usize::from(*byte)] += 1;
        }
    }
    let records = bytes.len() / RECORD_BYTES;
    let payload_bytes = records * 56;
    let entropy: f64 = histogram
        .iter()
        .filter(|n| **n > 0)
        .map(|n| {
            let probability = *n as f64 / payload_bytes as f64;
            -probability * probability.log2()
        })
        .sum();
    Ok(serde_json::json!({
        "scope": "Offline container structure and expected-hash comparison only",
        "bytes": bytes.len(),
        "sha256": sha256,
        "matches_expected_sha256": true,
        "record_bytes": RECORD_BYTES,
        "records": records,
        "sequential_big_endian_indices": true,
        "firmware_major": version >> 4,
        "firmware_minor": version & 15,
        "payload_bytes_by_historical_layout": payload_bytes,
        "payload_entropy_bits_per_byte": entropy,
        "checksum_verified": false,
        "signature_verified": false,
        "mcu_identified": false,
        "recovery_proven": false,
        "safe_to_flash": false,
    }))
}

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let path = PathBuf::from(
        args.next()
            .context("Usage: firmware_inspect FILE EXPECTED_SHA256")?,
    );
    let expected = args
        .next()
        .context("An independently recorded expected SHA-256 is required")?
        .into_string()
        .map_err(|_| anyhow::anyhow!("Expected SHA-256 must be ASCII hexadecimal"))?;
    ensure!(args.next().is_none(), "Unexpected extra argument");
    ensure!(
        std::fs::metadata(&path)?.is_file(),
        "Input must be a regular file"
    );
    let file = File::open(path)?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES as u64 + 1).read_to_end(&mut bytes)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&inspect(&bytes, &expected)?)?
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> Vec<u8> {
        let mut bytes = vec![0; RECORD_BYTES * 2];
        bytes[0] = 0x15;
        bytes[RECORD_BYTES] = 0x15;
        bytes[RECORD_BYTES + 2] = 1;
        bytes
    }
    fn hash(bytes: &[u8]) -> String {
        format!("{:x}", Sha256::digest(bytes))
    }

    #[test]
    fn structural_match_never_asserts_authenticity_chip_or_flash_safety() {
        let bytes = fixture();
        let result = inspect(&bytes, &hash(&bytes).to_uppercase()).unwrap();
        assert_eq!(result["records"], 2);
        assert_eq!(result["firmware_major"], 1);
        assert_eq!(result["firmware_minor"], 5);
        assert_eq!(result["payload_entropy_bits_per_byte"], 0.0);
        for field in [
            "checksum_verified",
            "signature_verified",
            "mcu_identified",
            "recovery_proven",
            "safe_to_flash",
        ] {
            assert_eq!(result[field], false);
        }
    }
    #[test]
    fn rejects_missing_data_trailing_bytes_and_oversize_inputs() {
        for bytes in [
            vec![],
            vec![0; RECORD_BYTES - 1],
            vec![0; RECORD_BYTES + 1],
            vec![0; MAX_BYTES + 1],
        ] {
            assert!(inspect(&bytes, &hash(&bytes)).is_err());
        }
    }
    #[test]
    fn rejects_different_content_even_when_record_shape_is_unchanged() {
        let mut bytes = fixture();
        let expected = hash(&bytes);
        bytes[10] ^= 1;
        assert!(inspect(&bytes, &expected).is_err());
    }
    #[test]
    fn rejects_invalid_expected_hashes() {
        let bytes = fixture();
        for expected in ["", "abc", &"z".repeat(64)] {
            assert!(inspect(&bytes, expected).is_err());
        }
    }
    #[test]
    fn rejects_mixed_versions_and_bad_big_endian_block_order() {
        for offset in [0, RECORD_BYTES, 1, 2, RECORD_BYTES + 1, RECORD_BYTES + 2] {
            let mut bytes = fixture();
            bytes[offset] ^= 1;
            assert!(inspect(&bytes, &hash(&bytes)).is_err());
        }
    }
    #[test]
    fn unknown_trailer_remains_unverified_even_with_a_matching_hash() {
        let mut bytes = fixture();
        bytes[59..61].copy_from_slice(&[0x12, 0x34]);
        let result = inspect(&bytes, &hash(&bytes)).unwrap();
        assert_eq!(result["checksum_verified"], false);
        assert_eq!(result["safe_to_flash"], false);
    }
}
