# PipeWire damage metadata audit

Damage-aware exact zone reuse could avoid repeated sampling when only part of
an image changes. This is conditional on trustworthy metadata and complete
tracking of every skipped source frame; it cannot be inferred from stable
presentation timestamps or unchanged PipeWire buffer IDs.

The new operator command `nanoleaf-stream-probe --damage-audit` negotiates
sixteen SPA damage rectangles on a single permission-mediated DMA-BUF stream.
It runs for eight seconds after portal setup, inspects **every dequeued buffer**,
including the ones the latest-frame drain discards, and releases buffers using
the existing synchronization rules. It does not read pixels, import/sample an
image, drive USB, change application settings or show a test window. Portal
permission tokens retain their normal private single-use replacement semantics.
The command is separate from `--worker`; normal capture negotiates and samples
exactly as before. No automatic reuse or new daily setting is enabled.

The aggregate census distinguishes absent metadata, malformed/out-of-bounds
rectangles or bad headers, empty damage, a full-frame rectangle, local rectangles
and missing/nonconsecutive sequence values. A fixed diagnostic 48-zone perimeter
reports the affected-count histogram; this is not the user's mapping and does
not inspect or change calibration. Unit tests exercise the distinctions,
intersection boundaries, negative/overflowing coordinates and sequence gaps.

## Findings

On this host's uncontrolled KDE 6.7.5 desktop, all **236** dequeued buffers in one
eight-second run reported full-frame damage, with no missing/invalid metadata
or sequence gaps. Consequently this workload demonstrates **no work we can
safely skip**. It does not establish that KWin always reports full-frame damage;
controlled static/local-window workloads remain a future test. The operator
build is separate from the installed recovery build. Numeric evidence:
[damage census](../perf/damage-metadata-2026-10-16/README.md).

KWin's exact 6.7.5 [stream implementation](https://github.com/KDE/kwin/blob/v6.7.5/src/plugins/screencast/screencaststream.cpp)
offers up to sixteen damage regions, writes the region returned by source
rendering, and collapses excessive rectangles to a bounding rectangle. Its
[output source](https://github.com/KDE/kwin/blob/v6.7.5/src/plugins/screencast/outputscreencastsource.cpp)
distinguishes buffer repair from collected scene/device damage, but also returns
an empty region on rendering failures. An empty damage list alone is therefore
insufficient proof of identical valid pixels. The SPA metadata
[contract](https://docs.pipewire.org/group__spa__buffer.html) terminates the region
array at an invalid entry or its allocated end; the audit uses the safe libspa
iterator with size bounds rather than introducing local pointer access.

Before promoting reuse, require CPU/full-sampling colour parity across local
changes, skipped buffers, source/layout/colour changes and discontinuities.
Missing or uncertain damage must force full sampling. Global letterbox analysis
also needs independent invalidation, and temporal calibration/dithering must
continue even if raw zone samples are reusable. A zero-affected-zone histogram
entry is diagnostic, never permission to skip these correctness requirements.
