# HDR capture on Hyprland: what is missing upstream

19 November 2026. Checked against Hyprland `v0.57.2` (`11cbc6c`) and `main`
(`5177d94`), xdg-desktop-portal-hyprland `v1.5.0` and the installed
wayland-protocols. Line numbers are for `v0.57.2`; `main` matches within a line.

The [experimental plugin](../tools/hyprland-hdr-capture/README.md) works around
items 1–3 for one opted-in program. These are notes for a feature request. The
Hyprland project does not accept AI-written pull requests, issues or
descriptions, and requires contributors to understand every change themselves,
so write any request in your own words.

## Background

On an HDR monitor (`cm = "hdr"`), Hyprland composes in linear light, sends the
monitor 10-bit PQ / BT.2020 (`Colorspace` = BT2020_RGB, `HDR_OUTPUT_METADATA`
set), and SDR content is placed at `sdr_max_luminance`. Every screen-capture path
(xdg-desktop-portal-hyprland, `ext-image-copy-capture-v1`, `wlr-screencopy`) runs
through `Screenshare::CScreenshareFrame` and receives SDR sRGB. Highlights above
SDR white are clipped: in the nested test, patches at 203, 465 and 1000 nits all
came back as 255.

## What Hyprland would need

1. **Offer more than 8 bits to clients that can use it.**
   `misc:screencopy_force_8b` defaults to true
   (`src/config/values/ConfigValues.cpp:606`), and
   `CMonitor::getPreferredReadFormat` (`src/output/Monitor.cpp:2428`) then turns
   10-bit monitor formats into `XRGB8888`. The session offers only that format
   (`src/managers/screenshare/ScreenshareSession.cpp:159-160`). Ask: offer the
   10-bit (or FP16) format as well, at least to colour-managed clients.

2. **Do not force the capture target to sRGB.**
   `CScreenshareFrame::beginCopy`, `copyShm` and `storeTempFB` tag the capture
   framebuffer with `DEFAULT_SRGB_IMAGE_DESCRIPTION` (80-nit reference)
   (`ScreenshareFrame.cpp:462`, `520`, `570`). The renderer then converts the
   source into sRGB. `renderMonitor` computes `IS_CM_AWARE` and passes
   `cmBackToSRGB = !IS_CM_AWARE` (`:220`, `:237`), but the flag only matters when
   the target has no description, and it always has one, so colour-managed
   clients get sRGB too. Ask: for a colour-managed client with a high-bit-depth
   buffer, render in the output's image description (or one the client asks for).

3. **Keep HDR in the capture source.**
   The per-monitor mirror that capture reads from is SDR on PQ outputs.
   `CMonitorResources::getMirrorTexImageDescription`
   (`src/output/MonitorResources.cpp:158-164`) returns sRGB for any transfer
   other than sRGB/gamma 2.2. With SDR brightness or luminance settings, the
   mirror is filled in the surface shader with a plain range clamp; the code
   says `// TODO HDR -> SDR tonemap` (`src/render/shaders/glsl/cm_helpers.glsl:253`).
   Ask: keep an HDR copy (or read the work buffer) for clients that receive HDR,
   and tone-map properly for the SDR copy.

4. **Tell the client what the buffer contains.**
   `ext-image-copy-capture-v1` has no event that describes a frame's colour
   encoding, and no extension for it was found in the installed
   wayland-protocols (staging has `color-management`, `color-representation`,
   `ext-image-capture-source` and `ext-image-copy-capture`). Without it a client
   cannot tell PQ from sRGB in a 10-bit buffer and must not guess. Ask: a way to
   announce the frame's image description (for example a
   `wp_image_description_v1` for the capture session). This is a
   wayland-protocols discussion as much as a Hyprland one.

5. **Carry it through the portal (xdg-desktop-portal-hyprland).**
   xdph already maps 10-bit DRM formats to SPA formats
   (`src/shared/ScreencopyShared.cpp:302-350`), but it sets no colour keys on the
   stream format and does not use colour management. PipeWire can describe it:
   `SPA_FORMAT_VIDEO_transferFunction` with `SPA_VIDEO_TRANSFER_SMPTE2084`, and
   `SPA_FORMAT_VIDEO_colorPrimaries` with `SPA_VIDEO_COLOR_PRIMARIES_BT2020`.
   Ask: once Hyprland provides 1–4, negotiate a 10-bit format and set those keys,
   so portal clients get HDR with explicit metadata and without opting in by
   name.

## Related: HDR content is dimmed unless it declares its range

Not a capture problem, but it decides what capture sees. Hyprland tone-maps a
PQ surface from its declared luminance maximum to the output's
(`src/render/Renderer.cpp:2179-2206`). PQ without `set_luminances` implies
10000 cd/m², and the default curve then lowers even SDR-level values (a 203-nit
patch showed at about 104 nits on a 465-nit output). Mastering metadata does
not change it. Clients can avoid it with `set_luminances`; whether Hyprland
should treat mastering luminance or MaxCLL as the content peak is a fair
question for upstream. Details and measurements are in the
[plugin README](../tools/hyprland-hdr-capture/README.md).

## Not in scope here

Plasma/KWin was not re-examined; its capture also produces 8-bit sRGB (see the
raw HDR section of `IMPROVEMENT_RESEARCH_2026-10-14.md`). Privileged DRM/KMS
scanout capture was rejected for privacy and security reasons: it bypasses
consent and redaction and needs `CAP_SYS_ADMIN`.
