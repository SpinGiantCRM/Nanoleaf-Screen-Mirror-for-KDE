# Offline receiver encoding evidence

See [findings and limits](../../docs/RECEIVER_ENCODING_FOLLOWUP.md).
No USB, network, firmware write or vendor-code execution occurs in the public
solver. This is development analysis, not an application Python dependency.

- `crc_constraints.py`: standard-library-only shared-symbol CRC elimination,
  bounded to 512 MiB / 90 CPU seconds and at most 1,024 complete records.
- `crc-constraints.json`: all eight conditional polynomial candidates, with and
  without a zero-tail hypothesis. Two remain consistent; no plaintext recovered.
- `finite-padding-keys.json`, `finite-literal-keys.json`, `finite-crc-keys.json`,
  `xxtea-crc-probe.json`: sanitized counts and negative finite decoder searches.
  No candidate reached a complete-image checksum validation.
- `source-hashes.json`: private finite-search script identities. Those scripts
  depend on local proprietary source locations and optional developer crypto
  libraries; neither their inputs nor candidate literals are published. The
  public checksum solver has no such dependency.

Run synthetic controls without any stock files:

```bash
python crc_constraints.py --self-test
```

For full reproduction, privately place the five pinned files named
`1.1.0.firmware` through `1.5.0.firmware` in one directory. Their exact hashes are
in the existing `software-reverse-engineering-2026-10-15/firmware-hypotheses.json`.
The tool rejects other hashes, partial records and excessive inputs:

```bash
nice -n 19 python crc_constraints.py /path/to/private/images
```

Only the checksum-constraint result is fully reproducible from these public
scripts and the pinned private firmware inputs. Finite-search result files are
retained observations, not a published exhaustive decoder implementation. No
firmware images, vendor code, candidate keys, serials, calibration, contact data
or raw USB traces are included. None of these results authorizes flashing or
identifies the MCU, cipher, recovery path or physical response time.
