# Vendor software reverse engineering

2026-10-15. Extends [closed-case firmware research](CLOSED_CASE_FIRMWARE_RESEARCH.md).

We have now traced the desktop USB path, disassembled its native calibration
library, reproduced selected colour routines in a CPU emulator, and exercised
selected transport methods against fake HID and a fake clock. **The controller
firmware itself has not been decoded.** No controller commands, firmware changes,
enclosure opening or live application tests were needed.

## Inputs and method

The inspected official installers are
[Desktop 3.0.1](https://desktop-app-prod-3.s3.us-west-2.amazonaws.com/Nanoleaf%20Desktop%20Setup%203.0.1.exe)
and [Desktop 2.2.4](https://desktop-app-prod-1.s3.us-west-2.amazonaws.com/Nanoleaf%20Desktop%20Setup%202.2.4.exe).
Their pinned hashes and the five firmware hashes are recorded in the preceding
reports. Vendor executables, DLLs, source excerpts and firmware remain private.
None is redistributed with these results.

JavaScript was parsed as syntax with Acorn 8.19.0, rather than searching only
names in minified text. The USB class and its method offsets are indexed against
the inspected source hash. Offsets are **UTF-16 code units**, as returned by the
JavaScript parser. PE imports, exports and sections were inspected statically.

Selected native colour arithmetic ran inside Unicorn 2.1.4, with bounded memory
and a maximum 100,000 instructions/one second per call. DLL startup, the Windows
loader, global calibration-map initialization and OS imports were not executed.
Three profile objects were constructed with the inspected internal constructor
and their read-only parameter structures. Only `fmaxf`, `fminf` and `round` are
implemented as mathematical substitutes; any other imported call fails. The
selected routines returned before the limits, without unsupported imports.

Two selected JavaScript transport methods were evaluated in a VM using fake
HID writes, an event emitter and manually advanced promises. The desktop app was
never launched. This is a controlled software trace, **not a USB hardware test**;
the VM is not being presented as a security boundary for arbitrary software.

## USB colour path

The inspected 3.0.1 path is:

```text
streamed zone colours
  -> serialized target update
  -> 30 Hz timer, guarded against overlapping timer callbacks
  -> transition towards target
  -> native hardware-profile calibration
  -> host brightness adjustment and minimum-channel mapping
  -> GRB TLV, split into 64-byte chunks, each with leading report ID zero
  -> serialized writes
  -> expected command-type acknowledgement
```

This path contains no discovered streaming bypass for acknowledgements. With
48 zones it uses the same three report sizes, **65/65/20 bytes**, as our existing
driver. Its timer introduces a phase wait of up to approximately **33.3 ms** for
an update that has reached the target state, before other processing/queue/device
costs. That is a code-derived scheduling interval, not an end-to-end measurement.
Our daily app does not need to adopt this timer or its transition behaviour.

The request helper registers a listener for the command plus `0x80`, writes the
reports, and resolves/rejects from that response's status. Its one-second sleep
serves a retry check; it does **not** force the already-resolved request to wait
one second. Five offline cases confirm:

| Fake input | Observed software behaviour |
| --- | --- |
| Success ACK at fake time 5 ms | Request resolves at 5 ms; a remaining timeout promise does not hold it open |
| No ACK | Whole request resent at 1,000 ms; timeout at 2,000 ms, six reports total |
| Error status | Request rejected |
| Another command's reply | Does not satisfy this listener |
| Two same-command requests, deliberately bypassing the serial queue | One ACK satisfies both listeners |

The last case explains the need for transaction serialization in the host
implementation. There is no frame sequence identifier in this correlation path.
It is not evidence that the real device accepts two frames at once, nor that an
ACK means the light has changed. The earlier physical overlap experiment remains
the hardware evidence against enabling overlap in our daily app.

The generic native HID module exports HIDAPI operations and uses Windows file
I/O; this inspected path does not reveal a separate chip-specific firmware
decoder. The other USB native-module copies have identical hashes. Native
capture-module strings identify Rust/N-API and Windows capture dependencies, not
the controller CPU. Such host build information cannot identify the MCU.

## Native colour processing

The JavaScript selects calibration profile 1 for NL82K2 hardware `1.0.0`, profile
2 for other NL82K2 hardware versions (including this unit's `1.1.0`), and profile
3 for NL82K1. These are vendor selection rules, not new runtime detection rules
or authorization to replace the user's saved calibration.

Disassembly establishes a hue/saturation table with **12 hue divisions and four
saturation divisions**, interpolation, a separate neutral path and separate CCT
tables. This is more than three fixed RGB gains. The wrapper copies the returned
three byte values into its output RGB integers. The exported function uses a
profile lookup; the emulator invokes the selected internal arithmetic directly
to avoid executing allocator/runtime initialization.

All six PE sections, including code and read-only tables, are byte-identical in
the two inspected calibration DLLs. The older file is 20,992 bytes, SHA-256
`f2f5103439593d50255ae0d7c12e551d4cd5fd00d6ddda1e09f7cb91ce7d8ca0`;
the newer file is 36,648 bytes, SHA-256
`a86758c34040055585436d2d96f15e21e084708815b3426a59c495fc97729a7e`.
The newer PE contains a 15,656-byte certificate table, explaining its larger
file size. This section comparison does not verify certificate trust.

### Reproduced neutral behaviour

For profiles 1 and 2, selected native arithmetic maps white to drive codes
`[255,174,131]`; profile 3 maps it to `[255,213,155]`. Black maps to zero at this
stage. These are **controller drive values**, not measured emitted colours.
Unequal drive values may compensate unequal LED output; they must not be judged
as a visual cast without measuring the strip.

An independent model matches all 256 neutral inputs on each of the three profiles:

```text
V = round(input_grey * 100 / 255)
output_channel = floor(profile_white_channel * V / 100)
```

Consequently, each native neutral ramp has **101 distinct RGB outputs**, rather
than 256. Input `[1,1,1]` becomes zero; profile 2 maps `[64,64,64]` to `[63,43,32]`
and `[128,128,128]` to `[127,87,65]`. This is a digital quantization finding, not
a photometric accuracy measurement. All ramps are monotonic by channel.

Validation includes **768 neutral model comparisons**, **768 identity checks**
with the native calibration-enable flag cleared, and 256 deterministic random
RGB inputs per profile, repeated with exactly matching outputs. Fourteen selected
colours per profile are included in the evidence. No unsupported OS import ran.
This is not a native Windows execution or full exported-API compatibility test;
CCT and every possible RGB input were not exhaustively validated.

### Host minimum-channel mapping

After calibration and brightness adjustment, both desktop versions map each
channel using `round(240 * channel / 255 + 15)`. A black calibrated frame therefore
has digital channel codes of 15 at this point, rather than zero. At full host
brightness profile 2's white drive values become approximately `[255,179,138]`
after that mapping (assuming the RGB/HSV round trip preserves integer RGB).

The reason for this minimum and its exact physical response are unconfirmed.
We do not infer a measured glow or a firmware black threshold from source alone.
It is not an appropriate reference to copy blindly: our black-to-off requirement
and saved calibration remain authoritative. Neither the vendor LUTs, percentage
quantization nor the floor were added to the app.

## Firmware encoding: additional negative evidence

The five stored images were tested for known UTF-16 device/manufacturer strings
under repeating XOR periods 1, 2, 4 and 8. Every tested period passed a synthetic
nonzero-key/nonzero-offset positive control; no firmware match was found. This
only excludes the searched strings under those masks. Missing strings, other
layouts and other encodings remain possible; it is not proof that all XOR
schemes have been excluded.

For changed eight-byte blocks at matching offsets between successive images,
mean Hamming distances are **31.86, 32.01, 31.98 and 31.95 bits out of 64**.
Minimum distances are 17, 20, 17 and 20 bits. Combined with exact repeated blocks,
this is consistent with investigating a deterministic block cipher, but **does
not identify a cipher or key**. Per-phase byte entropy remains high, and a fixed
XOR mask would preserve each phase's entropy. None of this produces readable MCU
code, a solved image checksum or an image that can safely be flashed.

The desktop updater still forwards prepared records, truncating its iteration
count with `floor(file_length / 61)`. It does not validate each stored CRC or
construct a custom image in the inspected host path. Loader-side checks may
exist; their implementation cannot be inferred from the host. The application
update contains no established backup of the loader or factory storage. Changing
clear headers, passing the container to a generic WCH tool or trusting a loader
product name would not establish recoverability.

## Practical consequences

- Keep our acknowledged serial transactions. The inspected 2.2.4/3.0.1 path
  offers no supported shortcut to send during the acknowledgement period.
- Preserve the app's response-focused scheduling and calibrated colour precision.
  Reproducing the vendor's timer, grey quantization or channel floor does not
  establish better colour reproduction on this unit.
- Retain vendor calibration as a digital comparison source only. Adopting its
  coefficients would need measured emitted-light improvement and regression
  evidence using the same physical strip, with saved calibration preserved.
- The next firmware milestone is an actual decoder/source or documented image
  format plus confirmed closed-case recovery. The manufacturer enquiry requests
  these. After the email address proved unmonitored, the approved questions were
  delivered through the technical support form; no recurring monitoring exists.

Full controller code disassembly, exact chip identification, LED signalling
timing and acknowledgement-to-light timing remain open. No firmware performance
benefit is claimed from these host-software results. Your enclosure, installed
app, settings, manual 48-zone mapping and native/Python fallbacks remain intact.

Reproducible scripts, input hashes and aggregate results:
[perf/software-reverse-engineering-2026-10-15](../perf/software-reverse-engineering-2026-10-15/README.md).

Later historical-driver analysis, support-form delivery and an explicitly
authorized raw-level test are recorded in [the follow-up](FIRMWARE_ENCODING_FOLLOWUP.md).
Its unresolved visual result does not establish a physical black threshold.
