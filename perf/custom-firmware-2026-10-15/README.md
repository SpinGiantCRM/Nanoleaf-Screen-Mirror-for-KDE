# Custom firmware recovery research

See [the report](../../docs/CUSTOM_FIRMWARE_RECOVERY.md).

The vendor's normal update check previously offered no newer version. A separate
metadata request reproducing the official client's empty-version recovery object
returned the stock 1.5.0 application update URL. This was HTTPS only; the strip
remained in normal application mode. The real USB serial was sent to the vendor
but is excluded from request metadata and this repository.

- `factory-image.json`: official URL, file size/hash and HTTP metadata; no image bytes.
- `offline-inspection.json`: actual Rust inspector output against that downloaded
  file. Structure/hash checks do not identify the MCU or authorize flashing.
- `recovery-availability.json`: sanitized recovery metadata request/response.
- `exterior-label.json`: model/power transcription from the user photograph;
  original photograph, serial and barcode excluded.
- `usb-descriptor-summary.json`: existing kernel attributes; no device transaction.
- `protocol-history.json`: revision/date and presence of the vendor demo/DFU
  documentation; no author IDs or full third-party documentation.
- `checksum-exploration.json`: 36 CRC parameter hypotheses and standard reference-vector checks; no matching trailer algorithm established.
- `checks.json`: local tests, preservation checks and explicit verification limits.

The stock image, downloaded manufacturer datasheet, static vendor-app extracts
and private build logs are retained outside the repository. There are no keys,
serial numbers, screen data, firmware payloads, erase/program scripts or
bootloader-entry commands in this evidence directory.
