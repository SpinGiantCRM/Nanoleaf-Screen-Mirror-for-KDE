# ACK-path evidence, 16 October 2026

See [the findings and limitations](../../docs/USB_ACK_PATH_EXPERIMENTS.md).

- `final-single.json`: 256 acknowledged generated full frames, ordinary writes
  versus one complete TLV in one host write, ABBA within each pattern.
- `final-output.json`: 256 acknowledged generated full frames, ordinary writes
  versus the output-report ioctl. Its `plan.true_means` defines the candidate.
- `final-pacing.json`: 256 acknowledged full frames with paired 0/250/500/1000/
  2000 us inter-report gaps.
- `final-brightness.json`: 192 acknowledged black/code-8 full frames, six raw
  controller brightness requests in forward/reverse order, including readbacks.
- `final-control.json`: rejected GET_REPORT experiment, idle empty read and
  pending ioctl timeout; ordinary transaction times out, restoration succeeds.
  The successful pending ACK was later drained before another command, as
  independently checked in the private syscall trace. Do not infer ACK loss.
- `summary.json`: per-case medians, nearest-rank p95, min/max and observation
  counts, with exactly two warmups excluded per case. No failed experiment is
  reclassified as a successful colour command. Total 960 measured successful
  full-frame colour commands, excluding setup/query/cleanup.
- `packet-shape.json`: a separate 384-command acknowledged ABBA experiment,
  reference versus final padding, 63-byte and 60-byte fragmentation.
- `packet-shape-summary.json`: 12 retained samples per pattern/layout/comparison,
  excluding two warmups per case. Reproduce with `python summarise_shape.py`;
  `python summarise_shape.py --check` also verifies the stored aggregate and rejects
  a missing-ACK negative control.

Packet-layout binary SHA-256:
`23a082a05b3e4c8720bdc308cca8a8561b61579deb30536d356834abb1e056e2`.
It is distinct from the five earlier experiments' binary below. Layout changes
preserve all declared TLV bytes; this does not constitute optical parity. No
layout improved command time; padded varied colours are about 1 ms slower.
Guarded cleanup/restoration and an independent power/brightness readback passed.

Final measurement binary SHA-256:
`555c3d45a6f9c4157833acc33a6526c3f2fc05d0e4edc26f3ffd8aae164354d3`.
All five final experiments use this one retained binary. Subsequent source edits
correct the control failure description and the raw-brightness diagnostic guard;
they do not produce the recorded timings. Earlier operator pilots are retained
privately and are not pooled. Measurements use userspace monotonic stage clocks;
syscall tracing adds overhead and does not timestamp optical output or exact
hardware packet arrival. This is not a controlled gameplay response benchmark.

The recorded pacing plan inherited an inapplicable generic one-write hypothesis,
and the brightness plan inherited a generic request-10 field. Per-case gaps,
actual brightness requests/readbacks and measured samples specify what ran.
Those plan-only metadata fields are corrected in source; recordings are retained
without rewriting them. The control failure's older wording does not establish
ACK loss; the trace finding above supersedes that interpretation.

Generated frame definitions, ABBA order, safety limits, explicit opt-in, exclusive
ownership and restoration are in `native/app/src/probe/ack_path.rs` and
`native/app/src/device/ack_probe.rs`. Every frame goes through the existing TLV
encoder and ordinary ACK validation. The daily path has no experiment selection
and continues to use normal reports. The installed pair was left unchanged.

No saved colour coefficients, screen contents, portal tokens, controller serial
number, firmware binaries, vendor source or raw traces are included here.
