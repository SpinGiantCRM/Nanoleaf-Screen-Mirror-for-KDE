# Offline firmware model and recovery follow-up

See [findings, assumptions and recovery limits](../../docs/FIRMWARE_MODEL_FOLLOWUP.md).
These operator tools use only the Python standard library. They have no USB,
network, vendor-code execution or firmware writer, and add no application dependency.

## Reproduce the public analyses

From the repository root, run generated positive and negative controls:

```bash
python perf/firmware-models-2026-10-16/analyse_models.py --self-test
python perf/firmware-models-2026-10-16/padded_tail.py --self-test
```

Both are included in CI and `scripts/release_gate.sh`. Controls include known
nonlinear substitutions, cross-byte affine transforms, an unknown generated
additive encoding, nonzero CRC initial/final constants and corrupted trailers.

For stock-file reproduction, privately supply the five files named
`1.1.0.firmware` through `1.5.0.firmware`, matching the pinned hashes in
[`firmware-hypotheses.json`](../software-reverse-engineering-2026-10-15/firmware-hypotheses.json).
Inputs are bounded and hash-checked; the combined analysis accepts at most 1,024
complete 61-byte records. These Linux CLI tools limit address space to 512 MiB
and CPU time to 90 / 60 seconds respectively:

```bash
nice -n 19 python perf/firmware-models-2026-10-16/analyse_models.py /path/to/private/images
nice -n 19 python perf/firmware-models-2026-10-16/padded_tail.py /path/to/private/images
```

The outputs reproduce `model-results.json` and `tail-results.json`. The bytewise
model permits arbitrary substitutions, including non-bijective ones. Period-8
consistency is an underdetermined fit, not a recovered substitution table. The
tail search assumes a uniform plaintext terminal record; it reports numerical
hypotheses only, never decoded code or keys. Its candidate count includes
redundant representations. Eight XOR-index permutations cover common byte/word
orders, not every possible permutation of eight bytes.

## Retained observations

- `decoder-order-followup.json`: finite private decoder search counts, optional
  developer crypto libraries, no surviving three-record candidate.
- `header-index-order.json`: repeated shared-symbol constraints with the index
  bytes swapped only in the proposed CRC input; no unique polynomial or order.
- `block-patterns.json`: equality classes and data-relative offsets, no opaque
  firmware bytes and no asserted CPU vectors.
- `solver-inconclusive.json`: bounded SMT/SAT outcomes, including timeouts and
  unsuccessful unknown-key controls. These do **not** exclude the models.
- `research-sources.json`: official model declaration provenance, generic loader
  sources, source/archive coverage limits and static UI recovery findings.
- `ui-member-provenance.json`: selected archive member names, sizes and verified
  hashes; no vendor source or translations.
- `source-hashes.json`: identities of private supplemental analysis scripts.

Only the two public analyses are fully reproducible from this directory and the
pinned private images. Supplemental searches retain observations and source
identities rather than publishing proprietary inputs or candidate literals.
No firmware images, keys, controller identifiers, signed download URLs,
calibration, raw USB traces or vendor source are included. No result establishes
chip identity, executable plaintext, independent recovery or flash readiness.
