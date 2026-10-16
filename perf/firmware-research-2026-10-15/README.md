# Firmware research evidence

See [the research report](../../docs/FIRMWARE_LATENCY_RESEARCH.md).

- `device-info.json`: fixed read-only HID identity queries using the exclusive
  output lease and unchanged manual configuration; no serial number.
- `research.json`: official installer URL/size/SHA-256 (never executed), protocol
  revision, static-inspection findings, metadata-only update-service responses,
  preservation checks and local test count.

The second vendor request used the real USB serial to identify this unit, as the
vendor updater does. The serial itself is excluded from evidence. HTTP 404 with
`update_status: none` is accepted/handled by that official updater. It means no
update offered for this request, not a universal latest-firmware guarantee.

Private installer/archive data, extracted proprietary application code, author
metadata, USB serials, config/calibration, screen pixels and portal tokens are
not committed. There is no firmware image, programmer or flashing command here.

Inspection used archive listings, the Electron ASAR header/file table and static
searches for NL82K2/USB update methods. Vendor code was not evaluated. Protocol
revision metadata came from Confluence's public content REST representation.
