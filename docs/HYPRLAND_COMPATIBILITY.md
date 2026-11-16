# Hyprland streaming compatibility

15 November 2026. The same desktop (RTX 4080 SUPER, NVIDIA 620.70 open driver,
Dell AW2725Q 3840×2160 at 240 Hz) was moved from Plasma to **Hyprland 0.57.2**
with **xdg-desktop-portal-hyprland 1.5.0** and PipeWire 1.6.11. Hyprland ran
HDR output (`cm = "hdr"`, 10-bit `XBGR2101010` scanout, SDR max 203 nits,
gamma22), VRR and scale 1.5.

The selected portal/Vulkan backend previously refused to start because the
worker required `org.kde.KWin` and a 6.7/6.8 version. KWin ScreenShot2 does not
exist on Hyprland. This change adds a separate, detected Hyprland contract. The
KWin branch, its version gate and its error text are unchanged.

## Detection

`native/stream-probe/src/compositor.rs` checks KWin first: if `org.kde.KWin` owns
its bus name, the original 6.7/6.8 gate applies unchanged. Otherwise the worker
asks the running Hyprland instance through
`$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket.sock` (`j/version`).
A stale environment variable without a live socket never selects Hyprland.
Only the probed 0.57 family is accepted; a later release must be re-probed and
its range widened deliberately. Any other compositor is refused.

## What xdph delivers (live probes)

`nanoleaf-native-capture --suite` and `--dma-buf-explicit`, plus a one-frame
GStreamer `pipewiresrc` capture of known sRGB patches (no images saved):

| Property | Hyprland 0.57.2 / xdph 1.5.0 |
| --- | --- |
| Format | `BGRA` (DRM ARGB8888), 8 bits per channel, 3840×2160 physical |
| Colour metadata | untagged: transfer, primaries, range, matrix all 0 |
| DMA-BUF modifier | NVIDIA block-linear `0x0300000000606014`, importable one-plane |
| CPU path | MemFd SHM buffers when DMA-BUF is not requested |
| Implicit sync | works (`implicit-sync-file`); GPU/CPU sample parity exact |
| Explicit sync | **not offered**: requesting SyncTimeline fails with `error alloc buffers: Invalid argument` |
| Portal stream properties | `mapping_id` = connector (`DP-1`), `position` logical, `size` **physical** |
| Restore token | returned only when the picker's "Remember this choice for future requests" box is ticked; then later starts skip the picker (26 ms) |

### Colour with HDR on

The composition is returned as SDR sRGB bytes, not PQ and not washed out.
Untagged sRGB test patches came back bit-exact through the portal: grey 16, 32,
64, 128, 192, white, pure red/green/blue, yellow and 128/0/0. So Hyprland's
screencopy renders SDR surfaces into an sRGB-encoded 8-bit target independently
of the HDR scanout, which is the same contract the application uses on KWin. No
PQ/HLG decoding or other display transform is applied. The per-frame guard
still rejects tagged non-sRGB metadata, and DMA negotiation still offers only
the one-plane BGRA modifiers.

`compositor_hdr_mode`/`hdr_transfer` remain inert settings on the stream path.
The unmeasured case is HDR-tagged client content (a PQ video or game surface).
How Hyprland maps that into the 8-bit capture is not verified; expect it to be
clipped or tone-mapped to SDR, never raw PQ.

## Behaviour differences handled

- **Monitor selection:** xdph reports physical size (3840×2160) while
  xdg-output gives logical size (2560×1440 at scale 1.5), so the KWin
  position/size match fails. The Hyprland branch matches the portal's
  `mapping_id` to exactly one Wayland output name (and the configured monitor
  if set).
- **Explicit sync:** `NANOLEAF_EXPLICIT_SYNC` is refused up front on Hyprland
  with a clear error instead of failing inside PipeWire.
- **Restore tokens:** stored per desktop (`portal-token` for Plasma,
  `portal-token-hyprland` for Hyprland), so alternating logins do not discard
  each other's remembered permission. xdg-desktop-portal binds a token to the
  caller's app ID: a token obtained by a helper started from a terminal or
  another app is rejected for the autostarted `org.spingiantcrm.NanoleafNative`
  and the picker is shown once. After the daemon itself was granted with
  "Remember", restarts restored silently (243 ms to mirroring) and rotated the token.
- **Lock monitoring:** Noctalia owns `org.freedesktop.ScreenSaver` for
  inhibition only and has no `GetActive`, which left the daemon waiting on
  "Desktop session monitoring unavailable". When the owner exists but answers
  UnknownMethod/Interface/Object, lock state now comes from logind's
  `Session.LockedHint` (`/org/freedesktop/login1/session/auto`). A missing owner
  still fails closed and retries; KWin implements `GetActive`, so Plasma is unchanged.
- **Login race:** autostart ran the daemon ~14 s after boot, before Noctalia
  owned `org.freedesktop.ScreenSaver`. The launch Start was refused as
  "monitoring unavailable" and the later SessionReady only changed the message,
  so the strip stayed off all day. A launch Start refused only by the session
  monitor is now retried once on SessionReady. A successful start, a Stop or any
  later lock/sleep interruption cancels that retry, so unlock/resume still never
  auto-starts.

## Live daemon result

Installed bundle, started through the XDG autostart unit under Hyprland:
`--status` reported `Mirroring`, backend `xdg-portal / Vulkan DMA-BUF / direct
SDR samples / implicit sync`, 50–123 acknowledged packets/s depending on screen
motion, fresh capture p50 0.75 ms, no missed deadlines.

## xdph frame-rate experiment

With a 240 fps synthetic video presenting every frame (mpv: 240 vf, display
239.99 Hz, no drops), the daemon received ~122 captured frames/s at xdph's
default `max_fps` (120). Setting `screencopy:max_fps` to 240 and then 0 was
negotiated (PipeWire `maxFramerate 240/1`, the worker's request from `fps = 240`),
yet delivery stayed at 122–124 fps across two 10-second runs each. xdph 1.5 on
this 240 Hz output delivers every other display frame; the limit is its copy
pacing, not a setting. Acknowledged USB updates (49–65/s) and screen-to-ACK
p50 (20–26 ms) were unchanged, so the default configuration was restored.

## Capture rate and desktop stutter

16 November 2026. While mirroring, a 60 fps live wallpaper dropped about one
frame every 1.5–2 s behind blurred ("glass") windows. Every frame xdph
captures makes Hyprland render the output again into an 8-bit SDR copy buffer,
and the worker requests `VideoMaxFramerate = fps` (240; xdph delivers ≤ ~120)
while the strip acknowledges only ~48 updates/s.

A 60 fps request was tried first. Over 10 s with the wallpaper, strip updates
(48.1 → 48.4/s) and fresh screen-to-ACK latency (p50 25.7 → 25.6–25.8 ms) were
unchanged, but the wallpaper's damage already limited capture to ~60/s, and
the drops remained. Then 240 fps recordings (`gpu-screen-recorder`, frame-diff
gaps over the glass region) were taken with mirroring on, off, and on again,
and were indistinguishable (2–8 gaps of 6 or more frames per 10 s in each,
depending on the threshold). The stutter is not caused by the capture.

The default request therefore stays at `fps`. A lower request would age the
frames the strip receives in high-frame-rate content, and flow outranks GPU
load. `NANOLEAF_CAPTURE_FPS=1..240` (bounded by `fps`) lowers the request for
experiments on either compositor.

## Limits

Physical LED colour and optical latency were not measured. Whether the lock
screen in use sets logind `LockedHint` was not tested (no lock was triggered);
if it does not, mirroring continues while locked. Hyprland/xdph
releases other than 0.57.x / 1.5.0 are not verified. If "Remember this choice"
is not ticked, xdph returns no restore token and shows its picker on every
capture start, including the worker restart after USB recovery.
