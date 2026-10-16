# Short USB payloads: bounded operator tests

16 October 2026. This extends [the active-zone investigation](USB_POSITION_AND_REPEAT_RESEARCH.md).
The daily transport still requires the complete authoritative manual zone count.
No production prefix trimming, overlap, calibration change or firmware operation
has been introduced.

## Protocol and safeguards

[Nanoleaf's documented command 0x02](https://nanoleaf.atlassian.net/wiki/spaces/nlapid/pages/2615574530/Nanoleaf+USB+Lightstrip+Communication+Protocol)
permits variable-length RGB payloads divisible by three. It does not specify
whether omitted zones retain their colours, turn off, repeat another value or
change device length. A successful ACK cannot answer that optical question;
there is no documented per-zone colour readback in this protocol.

The new operator command is plan-only unless explicitly run:

```bash
# Existing config, hardware-free plan:
native/app/target/release/usb_bench CONFIG --short-payloads
# Bounded timing probe, exclusive strip ownership:
native/app/target/release/usb_bench CONFIG --short-payloads --run
# One separately announced human observation; omit --run to preview its plan:
native/app/target/release/usb_bench CONFIG --short-payloads --observe red-prefix --run
```

Stop mirroring before running. The probe accepts manual counts 8–255 and only
nonempty prefixes shorter than that count. Raw channels are capped at64. It uses
the saved channel order and ordinary exact-length TLV/HID framing, with a serial
ACK for every command and no speculative write/retry. The short encoder is
crate-private and operator-only; `Strip::frame` and core full-frame validation
remain unchanged. The handle's manual count is never changed to the prefix size.

The existing guarded owner snapshots controller power/brightness, requests raw
brightness10, clears all manual zones, powers on, then runs the experiment.
Returned errors still attempt **full-count black cleanup** and restore both
original controls with readback. Physical disconnection or terminating the
process can defeat restoration. Previous colours cannot be queried/restored.
Raw brightness requests/readbacks are not optical percentage measurements.

## Actual acknowledged USB timings

The 48-zone NL82K2 (firmware query0x15) completed **768 measured transactions**,
with another768 full-black preconditions. Requested brightness10 read back16 in
all64 cases. Each measured command follows a full48-zone black command. Twelve
samples per case, first two uniformly excluded; full→short and short→full pair
orders are retained separately. Inputs are generated raw neutral codes8 and64,
not screen capture or the saved calibrated colour pipeline.

Representative forward-pair medians at raw neutral64:

| Written prefix zones | Full48 with black tail, total | Short, total | Short HID reports |
| ---: | ---: | ---: | ---: |
| 1 | 6.998 ms | 2.999 ms | 1 |
| 12 | 11.000 ms | 6.999 ms | 1 |
| 20 | 13.000 ms | 10.000 ms | 1 |
| 21 | 13.001 ms | 11.000 ms | 2 |
| 24 | 14.002 ms | 11.998 ms | 2 |
| 41 | 19.004 ms | 18.001 ms | 2 |
| 42 | 19.004 ms | 19.002 ms | 3 |
| 47 | 21.002 ms | 21.002 ms | 3 |

The64-byte TLV report boundary is crossed at21 and42 zones (three-byte header
included). Full writes were about3.98ms; short writes about1.97–2.00ms for one
report,2.97–3.00ms for two and3.96–3.97ms for three. Some small prefixes also
reduced ACK wait; the report-count saving alone does not explain every difference.
The reverse order confirms the representative12/24/47-zone results. All768
measured commands had one response report and no stale drained reports.

[All samples and per-order distributions](../perf/short-payload-2026-10-16/README.md)
are retained. These are host-observed command durations, not emitted-light timing,
continuous application FPS or whole-system power. Black preconditioning helps
control earlier state but does **not** independently establish omitted-zone
semantics. A shorter command is not demonstrated colour-equivalent merely
because it is acknowledged faster.

After the run, full-black cleanup and original controller restoration succeeded;
independent identity/power/brightness queries matched, including the diagnostic
reported count48. All13 preserved config/launcher paths remained unchanged.
The installed native app/helper and Python fallback were not upgraded or edited.

## Separately announced visual checks

Each step holds a full seed for three seconds, issues exactly ONE12-zone command,
then waits eight seconds without refresh before full48-zone cleanup/restoration:

- `red-prefix`: full blue64, then red64 on the first12 zones. Look for the
  remainder staying blue, turning off, becoming red or behaving unexpectedly.
- `black-prefix`: full red64, then black on the first12 zones. This distinguishes
  prefix-only black from a whole-strip blackout.
- `green-prefix`: full black, then green64 on the first12 zones. This checks
  whether old colours reappear or output extends beyond the supplied prefix.

The first red-prefix run was acknowledged and its restoration independently
verified. **Its human observation is pending; omitted-zone semantics remain
unresolved.** Do not turn a missing answer into an optical success. The remaining
steps wait for that report so observations are not confused with another run.

Even a positive report would establish only this tested model/firmware/count,
levels and idle interval. General production use would also require same-state
colour comparisons, dithering-safe selection of the last changed zone, connection/
control invalidation and full refresh/recovery tests. No offset/sparse-zone
addressing is documented: a prefix cannot directly update only a late zone.

## Software verification

123 native application tests pass (two operator tests ignored), including strict
full-frame rejection, short channel-order encoding, invalid/empty/oversized/high
code rejection, plan-only CLI paths, report-boundary coverage and error cleanup.
Warnings-denied GUI/all-target Clippy and formatting pass. The independent
Rust1.77 core's26 tests pass. Capture/GPU/colour code is unchanged, and no
photometric accuracy or optical-speed improvement is claimed.
