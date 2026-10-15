# Offline vendor-software reverse engineering

2026-10-15. [Report](../../docs/VENDOR_SOFTWARE_REVERSE_ENGINEERING.md).
No device access, Windows app launch or installed-app change. The scripts here
are operator research tools, not dependencies of the native app or its package.
Vendor code/images/DLLs are not redistributed. Preserve your private inputs.

## Reproduction

Use an isolated Python environment with **Unicorn 2.1.4** and **pefile 2024.8.26** installed.
The emulator refuses any calibration DLL other than the pinned 3.0.1 file. It
emulates selected instructions, not Windows DLL startup. A call stops after
100,000 instructions or one second; unimplemented imported calls fail.

```sh
python emulate_vendor_colour.py /PRIVATE/3.0.1-libColorCalibration.dll
python firmware_hypotheses.py /PRIVATE/images
node trace_vendor_transport.mjs /PRIVATE/asset-1.txt /PRIVATE/acorn.mjs
```

`images` contains the privately downloaded `1.1.0.firmware` through
`1.5.0.firmware` files, whose hashes are pinned in `firmware-hypotheses.json`.
Do not substitute other firmware or remove safety flags to make a test pass.
These programs output JSON to stdout; they do not write firmware or contact a
device. Negative tests can use a small local dummy file in place of the DLL/JS
or one firmware file; a changed hash must be rejected.

To obtain private source inputs, extract only the known archive members from
the pinned official installers: `$PLUGINSDIR/app-64.7z`, then
`resources/app.asar` and `resources/app/lib/win32-x64/libColorCalibration.dll`.
Read the ASAR index as data and extract its `minified/main.js` member. The
local research copy is named `asset-1.txt`; confirm the hash in
`usb-method-index.json`. ASAR member names may vary between releases; other
versions are deliberately refused by these probes. Use the Acorn 8.19.0 ESM
parser, whose distribution provenance is recorded in `parser-provenance.json`.
No bundled vendor executable or full desktop JavaScript entry point is run.

The transport harness parses the whole JS file, then selects just the two
inspected USB transport methods into a minimal class with fake HID and clock.
The deliberately concurrent case bypasses the vendor's serial queue to expose
the unnumbered reply ambiguity; it is not a recommendation to do this on USB.
Fake milliseconds are test inputs, not latency measurements.

## Evidence

- `emulated-colour.json`: selected digital outputs, 768 independent neutral
  comparisons, 768 disabled-calibration identity checks, repeated RGB samples.
- `colour-library-comparison.json`: file/section hashes and exported function
  addresses; all six sections match between 2.2.4 and 3.0.1.
- `mock-transport.json`: five fake HID/clock cases using the selected methods.
- `firmware-hypotheses.json`: synthetic XOR controls, negative string probes,
  per-phase entropy and changed-block Hamming distances; no cipher identification.
- `usb-method-index.json`: parsed class/method offsets, measured in UTF-16 units.
- `native-module-provenance.json`: native module hashes and bounded static findings.
- `checks.json`: reproduction, lint, rejection and preservation checks for this
  research change, separate from previous app regression results.

No optical colour accuracy, physical USB timing, raw HDR, reconnect behaviour or
custom firmware acceptance was newly tested. Digital white compensation is not
an emitted-light measurement. The daily app's calibration and fallbacks stay intact.
