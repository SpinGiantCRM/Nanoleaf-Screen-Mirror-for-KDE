# HDR screen capture on Hyprland (experimental plugin)

Hyprland 0.57.2 always gives screen-capture clients standard-range (SDR) sRGB
pictures, even when the monitor runs HDR. Highlights brighter than SDR white
(203 nits on an HDR desktop) are clipped before any capture client sees them.
This directory holds a Hyprland plugin that does two things:

- lets **one opted-in program** receive the monitor's real HDR picture
  (PQ / BT.2020, 10-bit) instead of the SDR copy, and
- stops Hyprland from **dimming HDR content** from Vulkan apps (games, video
  players, HDR wallpapers): see [content peak](#why-hdr-content-looks-dim).

It also holds test tools.

This is a local, experimental tool. Nanoleaf Screen Mirror does not use it yet:
the app's sampler accepts SDR sRGB only, and mapping HDR to LED output is separate
work. Nothing here is part of the release bundle or the release gate.

The code was written by an AI assistant (Claude). Read it before you load it into
your compositor. It must not be submitted to Hyprland: see
[upstream requests](../../docs/HYPRLAND_HDR_CAPTURE.md) for what to ask for there.

## What the plugin changes

### HDR capture

Only while an opted-in client captures a PQ HDR monitor into a 10-bit buffer:

1. **Format.** `misc:screencopy_force_8b` (on by default) limits every client to
   8-bit. The plugin adds `XBGR2101010` to the opted-in client's format list
   only. Every other client's list is unchanged.
2. **Source.** After Hyprland saves its normal SDR mirror copy for capture, the
   plugin also copies the composited frame into its own 10-bit framebuffer,
   tagged with the monitor's own image description (PQ). It stops copying 2 s
   after the last opted-in frame and frees the buffer.
3. **Target.** For the opted-in client's frames, the capture buffer is tagged
   with the monitor's description and the plugin's framebuffer is used as the
   source, so the copy is PQ to PQ with no conversion.

Hyprland's own capture code still runs for every frame: screen-sharing
permission, region crops and `noscreenshare` redaction are unchanged. Other
clients (the portal, OBS, `grim`) keep getting the same SDR picture.

Opt-in is by executable name: the client's `/proc/<pid>/exe` basename must be in
`plugin:nanoleaf_hdr:clients` (default `nanoleaf-hdr-probe`), and the process
must run as the same user as Hyprland.

### Content peak (`plugin:nanoleaf_hdr:content_peak`, on by default)

When a PQ surface declares no luminance range but does declare MaxCLL or a
mastering peak, Hyprland's tone-mapping decision for HDR targets uses that peak
instead of 10000 cd/m². SDR targets (an SDR monitor, sRGB capture) and surfaces
that declare a range are unchanged. This changes what the screen shows, so
every capture of the screen sees it too.

## Build

Needs the headers of the running Hyprland (`pkg-config hyprland`), a C++23
compiler, `wayland-scanner` and `wayland-protocols`.

```bash
make -C tools/hyprland-hdr-capture/plugin
```

```bash
make -C tools/hyprland-hdr-capture/probe
```

The plugin refuses to load unless it was built against the running Hyprland's
headers and that Hyprland is `v0.57.2`. Hyprland plugins have no ABI stability:
rebuild after every Hyprland update, and re-check the hooks before widening the
version check.

## Use

Load it into the running session (it is gone after logout):

```bash
hyprctl plugin load "$PWD/tools/hyprland-hdr-capture/plugin/nanoleaf-hdr.so"
```

Check what it delivers. Clients should read this before treating a frame as PQ:

```bash
hyprctl nanoleafhdr
```

`pq_outputs` lists each PQ monitor with transfer, primaries and luminances;
`armed` shows monitors with a live HDR copy; `counters.hdr_frames` counts frames
delivered from it, and `converted_frames` counts opted-in frames that Hyprland
converted from its SDR mirror because the HDR copy was not ready yet (still
correctly PQ-encoded, but without highlights above SDR white).

Capture one frame and print numbers only (nothing is saved):

```bash
tools/hyprland-hdr-capture/probe/nanoleaf-hdr-probe --output DP-1
```

`--patch X,Y,W,H` adds the mean code and PQ luminance of a region.

Unload:

```bash
hyprctl plugin unload "$PWD/tools/hyprland-hdr-capture/plugin/nanoleaf-hdr.so"
```

To load it at every login, a Lua config can call `hl.plugin.load(path)`. Load
it from a stable copy (for example `~/.local/lib/nanoleaf-hdr/nanoleaf-hdr.so`),
not the build directory, and rebuild and re-copy after every Hyprland update.

## Tests

`test/nested-test.sh` runs everything inside a **nested** Hyprland window, never
the running desktop. It forces the nested output to PQ HDR, shows
`nanoleaf-hdr-ladder` (a colour-managed test window with grey patches at 100,
203, 465 and 1000 nits) and captures it with and without the plugin. Optional
arguments: output peak, the pattern's mastering peak, and its declared luminance
range.

```bash
tools/hyprland-hdr-capture/test/nested-test.sh
```

Results on 19 November 2026 (Hyprland 0.57.2, RTX 4080 SUPER, NVIDIA 620.70):

| Patch shown | Normal 8-bit capture | Plugin, output peak 10000 nits | Plugin, output peak 465 nits |
| --- | --- | --- | --- |
| 100 nits (PQ 520) | 255 | 520 = 100.2 nits | 481 = 68.2 nits |
| 203 nits (PQ 594) | 255 | 594 = 202.9 nits | 524 = 104.2 nits |
| 465 nits (PQ 684) | 255 | 684 = 464.4 nits | 562 = 150.1 nits |
| 1000 nits (PQ 769) | 255 | 769 = 998.9 nits | 588 = 191.8 nits |

- With no tone mapping (peak 10000), the plugin returned every patch code exactly.
- With a 465-nit peak like the real monitor, the patches stay distinct and in
  order but come back lower. That is Hyprland tone-mapping the PQ window into
  its composition before display; the plugin copies that composition. Whether
  the real monitor shows the same values was not measured.
- Normal capture by another client was the same with the plugin loaded,
  unloaded or never loaded. Load, unload and capture did not crash the nested
  Hyprland.
- Fullscreen HDR windows can be scanned out directly, skipping composition;
  the plugin then has nothing to copy. mpv's Vulkan HDR output was not tagged in
  a way Hyprland honoured, so it was not usable as a test source.

### Live desktop (19 November 2026)

Loaded into the running Hyprland on the 3840×2160 PQ desktop (465-nit peak,
203-nit SDR white, scale 1.5) while Nanoleaf mirrored through the portal:

| Patch shown | Normal 8-bit capture | Plugin |
| --- | --- | --- |
| 100 nits | 223 | 474 = 63.6 nits |
| 203 nits | 255 | 518 = 98.3 nits |
| 465 nits | 255 | 555 = 140.4 nits |
| 1000 nits | 255 | 581 = 179.6 nits |

- The plugin loaded, captured and unloaded without trouble. Nanoleaf kept
  mirroring (48–50 updates/s, no missed deadlines), and other clients' captures
  were identical with the plugin loaded and unloaded.
- The values match the nested 465-nit test: Hyprland tone-maps the test pattern.
- With the wallpaper and windows on screen (before the pattern opened), nothing
  was above 203 nits.

### Why HDR content looks dim

Hyprland 0.57 tone-maps a PQ surface from its declared luminance maximum to the
output's. A PQ description without `set_luminances` implies 0.005–10000 cd/m²,
so Hyprland compresses everything, including SDR-level values (203 → 104 nits).
Mastering metadata (`set_mastering_luminance`, `set_max_cll`) does not change
this (`src/render/Renderer.cpp:2179-2206`, `tonemap.glsl`).

Vulkan apps cannot avoid it. With `VK_COLOR_SPACE_HDR10_ST2084_EXT` and
`vkSetHdrMetadataEXT`, the NVIDIA 620.70 driver sends `set_tf_named(st2084_pq)`,
`set_primaries_named(bt2020)`, mastering primaries, `set_mastering_luminance` and
`set_max_cll`, never `set_luminances` (logged with `WAYLAND_DEBUG` from mpv).
The `content_peak` hook fixes this case. Nested test, output peak 465, without
the hook:

| Patch shown | No range declared | `--luminance 465` | `--luminance 1000` |
| --- | --- | --- | --- |
| 100 nits | 68.2 | 100.2 | 79.2 |
| 203 nits | 104.2 | 202.9 | 137.8 |
| 465 nits | 150.1 | 464.4 | 256.1 |
| 1000 nits | 191.8 | 998.9 | 464.4 |

With the `content_peak` hook (MaxCLL and mastering peak declared, no range):

| Patch shown | Peak 465 declared | Peak 1000 declared | Nothing declared |
| --- | --- | --- | --- |
| 100 nits | 100.2 | 79.2 | 68.2 (unchanged) |
| 203 nits | 202.9 | 137.8 | 104.2 (unchanged) |
| 465 nits | 464.4 | 256.1 | 150.1 (unchanged) |
| 1000 nits | 998.9 | 464.4 | 191.8 (unchanged) |

Live desktop, plugin 0.2.0 loaded (19 November 2026), test pattern unfocused:

| Patch shown | Peak 465 declared | Nothing declared |
| --- | --- | --- |
| 100 nits | 94.5 | 63.6 |
| 203 nits | 190.0 | 98.3 |
| 465 nits | 435.8 | 140.4 |
| 1000 nits | 938.1 | 179.6 |

Every live value is 0.94 of the nested one: the desktop dims unfocused windows
(`decoration:dim_inactive`, strength 0.06). Nanoleaf kept mirroring with no
missed deadlines.

Content above the display peak is still tone-mapped, and Hyprland's default
curve then lowers mid-tones too (203 → 138 for 1000-nit content). The plugin
does not change the curve; a `tonemap` window rule can, for windows only.

```bash
tools/hyprland-hdr-capture/test/nested-test.sh 465 465
```

Arguments: output peak, the pattern's MaxCLL/mastering peak, its luminance range.

## Not verified

- An HDR game or video on the real desktop.
- The `content_peak` hook's first draft crashed the nested Hyprland: this
  Hyprland build leaves an unused argument uninitialised, so hooks must never
  copy their arguments.
- Direct scanout of fullscreen windows, the cursor plane, and DMA-BUF capture
  (the probe uses shared memory).
- Effects applied in Hyprland's final output pass (`decoration:screen_shader`,
  CTM changes) are not in the copy.
- Monitors other than one 10-bit PQ output, and Hyprland releases other than 0.57.2.

## Safety

A plugin runs inside Hyprland. A bug can crash the compositor and end the
session, and the first draft of this one did crash the nested test (fixed). The
plugin adds no new way to read the screen: the client must still open a normal
capture session, which Hyprland's permission rules govern, and redaction is
unchanged. It only changes the colour encoding for the named program.
