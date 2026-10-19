# Closed-case firmware evidence, 2026-10-15

See [report](../../docs/CLOSED_CASE_FIRMWARE_RESEARCH.md). All analysis is offline.
Files here contain aggregate metadata and our checksum hypothesis search, without
vendor executable bytes, serials, screen content or private correspondence.

- `historical-comparison.json`: hashes, sizes, record structure, data entropy and
  cross-version repetition counts for official 1.1.0 through 1.5.0 containers.
- `offline-inspections.json`: five successful pinned-hash inspections; all
  checksum/signature/MCU/recovery/flash-safety flags remain false.
- `updater-comparison.json`: static 2.2.4/3.0.1 updater observations; no update run.
- `crc-polynomial-analysis.json`: tested codeword layouts and positive control.
- `cross-version-crc-all-pairs.json`: conditional equal-data checksum differences;
  only two independent header differences, eight remaining candidates.
- `crc-effect-search.c`: reproduce those candidate parameters without input files:

```sh
cc -O2 -Wall -Wextra -Werror crc-effect-search.c -o /tmp/nanoleaf-crc-effect-search
/tmp/nanoleaf-crc-effect-search
```

The search assumes 59-byte messages whose first byte differs by 03/07 and whose
remaining bytes are equal. It compares the corresponding linear CRC differences
with observed trailer XORs, testing all nonzero 16-bit polynomials, both shift
directions and both trailer byte orders. Output contains eight candidates; it
does not determine a seed/final XOR or validate a firmware image. Raw SHA matches
pin research inputs, not authenticity, board compatibility or flash safety.

`checks.json` records this follow-up's validation separately from the preceding
95-app-test result. No daily application code changed and no hardware test ran.
