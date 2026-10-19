# GPU host-wait experiment: keep the existing default

The [per-update response measurements](RESPONSE_TAIL_DIAGNOSTICS.md) found capture
tails alongside parent USB backpressure. Colour finishing was already small.
This follow-up targets repeated host waits around the imported screen image.
It does not overlap USB commands, raise FPS, change colour calculations or enable
the experimental precise cached-source timer.

## Ownership and completion contract

The same Vulkan acquisition and release barriers remain, with unchanged image
layouts, foreign/local queue families, access masks and `ALL_COMMANDS` scopes.
All submissions still go through the same wgpu queue; no raw parallel submission
or extra in-flight screen buffer is introduced. Producer synchronization remains
mandatory in both implicit and explicit modes.

In the experiment, a cached image's acquisition barrier is submitted without immediately
waiting on the CPU. The following analysis/readback depends on that barrier on
the same queue. Initial imports retain their original completed-acquisition
construction contract. On a successful callback the redundant pre-release host
wait is omitted; the **final release submission is always waited to completion**
before returning the dequeued PipeWire buffer or signalling its release timeline.
Error callbacks retain the original extra completion check. Timeouts remain
bounded and terminate the isolated helper rather than requeue uncertain memory.

This uses Vulkan's explicit barrier scopes and final completion guarantee, not
an assumption that submission order alone serializes execution. The relevant
contracts are [Vulkan synchronization](https://docs.vulkan.org/spec/latest/chapters/synchronization.html#synchronization-pipeline-barriers)
and [queue-submission fences](https://docs.vulkan.org/spec/latest/chapters/synchronization.html#synchronization-fences-signaling).
The guarded raw encoder remains within
[wgpu's HAL interop boundary](https://docs.rs/wgpu/30.0.1/wgpu/struct.CommandEncoder.html#method.as_hal_mut).

`NANOLEAF_BATCH_GPU_WAITS=1` enables this operator experiment. It is **off by
default** and has not been installed or enabled on the daily app. Backend
attribution adds `batched waits` only when enabled. There is no additional
settings/FPS knob. A temporary default-enabled comparison build used
`NANOLEAF_SERIAL_GPU_WAITS=1` for its control; that variable is not used by the
retained implementation, and that build must not be installed as the daily app.

Do not compare acquisition-stage duration alone: deferring a wait moves some of
its cost into the following readback. Compare total completed capture work.

## Measurements and limits

The exploratory prototype used three AB/BA pairs of eight-second real capture
probes on the RTX 4080 SUPER, discarding the first 32 fresh outputs per run.
Validation/parity were disabled in timings and tested separately. All three pairs
had lower total-capture medians with batching. Median of run medians was
1.209 ms with the previous sequence and 0.967 ms with batching; corresponding
95th-percentile medians were 2.736 and 2.496 ms, and 99th-percentile medians were
3.631 and 3.116 ms. Separate prototype probes verified 717 exact complete-colour
outputs, with clean Vulkan validation, in implicit and explicit synchronization.

This is a modest stage improvement on an uncontrolled desktop, not a demonstrated
optical response gain, whole-application CPU improvement or fixed power saving.
The larger content-dependent USB transaction remains. No camera was available;
no new emitted-light, USB-unplug, suspend or permission-revocation claim is made.

A second set of three AB/BA pairs did not reproduce a consistent gain. The
control median of run medians was 1.108 ms and batching 1.355 ms; corresponding
95th-percentile medians were 4.059 and 2.939 ms. Individual paired results included
regressions, including one batched median of 4.263 ms versus its control 1.108 ms.
Desktop workload was uncontrolled, so neither a causal regression nor a reliable
gain is established. **Do not promote this from the first favourable comparison or
from the acquisition-stage timing alone.** Keep the current default and use a
controlled source/GPU workload before reconsidering it.

The second build also passed 699 exact complete-colour outputs across implicit
and explicit modes, clean Vulkan validation and both lifecycle/recovery probes.
Those correctness results establish neither a speedup nor an optical gain. The
retained opt-in code keeps initial and final ownership waits mandatory, covered
by an explicit headless contract test.

Both paired comparisons, correctness/recovery and package evidence
are under [`perf/gpu-wait-batching-2026-10-15`](../perf/gpu-wait-batching-2026-10-15).
Generated colour maths and calibration/configuration are unchanged. Previous
immutable native versions and the Python fallback remain available.

To reproduce without USB output, use the same selected monitor, configuration,
moving test scene and GPU workload, alternating these bounded probes:

```bash
bundle/bin/nanoleaf-native --stream-capture-probe /path/to/config.toml 8
env NANOLEAF_BATCH_GPU_WAITS=1 bundle/bin/nanoleaf-native --stream-capture-probe /path/to/config.toml 8
```

Discard the first 32 fresh outputs in each run and compare total `capture_ms`
for the remaining fresh outputs, keeping cached outputs separate. Collect at
least three AB/BA pairs, retain individual results and identify the executable
hashes. Run `NANOLEAF_STREAM_PARITY=1 NANOLEAF_VULKAN_VALIDATE=1` separately for
correctness; its full-frame readback cost must not enter performance timings.
