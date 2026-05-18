# Research: ICC Profile Support + Performance Optimization

Date: 2026-05-18
Type: Research findings / implementation plan

---

## PART 1: ICC Profile / Display Gamut Integration

### Current State

The entire color pipeline hardcodes sRGB primaries and gamma throughout:

| File | Function | Assumption |
|------|----------|-----------|
| `color/hdr.py:28-53` | `_XYZ_TO_SRGB`, `_BT709_TO_XYZ`, `_BT2020_TO_XYZ` | Matrix conversions only for BT.709 and BT.2020. No P3/AdobeRGB |
| `color/hdr.py:218-291` | `convert_frame_to_srgb8()` | Default path returns early for uint8+srgb+bt709 |
| `runtime/color_processing.py:102` | `rgb_u8_to_oklch()` | Calls `srgb_u8_to_linear01()` — hardcodes sRGB gamma |
| `runtime/compositor.py:32` | `apply_sdr_boost_compensation()` | Assumes sRGB linearization |
| `color/hdr.py:241` | fast-path early return | Skips ALL color conversion if already sRGB |

If the user has a wide-gamut display (Display P3, Adobe RGB, BT.2020) and captures via kmsgrab (which produces the display's native format), colors will be over-saturated or shifted when interpreted as sRGB.

### How to Detect Display Gamut on Linux

Four approaches ranked by reliability:

#### A. Wayland color-management-v1 protocol (best for Plasma 6+)
- New protocol: `wp_color_manager_v1` → `wp_image_description_v1` on the output
- Returns CIE 1931 xy chromaticity coordinates or named primaries
- Can also return ICC profile as a file descriptor (fd)
- Python bindings via `python-wayland`
- **Status**: KWin supports this since Plasma 6.1

#### B. colord D-Bus API (most portable)
- System service `org.freedesktop.ColorManager`
- `colormgr get-devices` lists displays; each has profile with ICC profile path
- Python: `dasbus` or `pydbus` (whichever the project already uses)
- KDE Plasma integrates with colord via `colord-kde`
- **Status**: Works on X11 and Wayland

#### C. Raw EDID parsing (no deps, always available)
- `/sys/class/drm/card*-*-*/edid` — 128-byte EDID blobs
- Chromaticity coords at offsets 0x19-0x22
- Python: `pyedid` or manual struct parsing
- **Drawback**: EDID gamut data may be manufacturer defaults

#### D. X11 fallback
- `xprop -display :0 -root _ICC_PROFILE`

### How to Convert Between Color Spaces

**Approach 1: 3x3 matrix in linear RGB (recommended)**
- Same pattern as existing BT.709→sRGB and BT.2020→sRGB in hdr.py
- Known matrix for Display P3 D65 → sRGB
- ~95% accuracy, no new dependencies, fast
- Add to `color/primaries.py`

**Approach 2: Pillow.ImageCms (full ICC pipeline)**
- `PIL.ImageCms.buildTransform(src, dst, "RGB", "RGB")`
- Ship with Pillow, uses LittleCMS2
- Handles LUT-based profiles
- Requires PIL Image round-trip → memory copy

**Approach 3: pylcms2 (direct numpy CMM)**
- Works directly on numpy arrays
- Can create built-in profiles
- New pip dependency

### Recommended Implementation

```
New files:
  src/nanoleaf_sync/color/display_gamut.py   — detect display primaries
  src/nanoleaf_sync/color/primaries.py        — gamut matrices

Changes:
  color/hdr.py:28-53             — Add P3/AdobeRGB matrices
  color/hdr.py:218-291            — Accept P3/AdobeRGB in convert_frame_to_srgb8()
  runtime/engine.py:404           — Wire gamut conversion path
```

**Detection priority**: colord D-Bus → EDID → assume sRGB

---

## PART 2: Performance Optimization

### Finding: SDR boost runs on full-resolution frame (Major Win)

**File**: `runtime/engine.py:403-409`

SDR boost runs `srgb_u8_to_linear01()` + division + re-encode on the **entire frame** (1920x1080). Zone sampling at line 413 then averages down to ~128 colors.

**Fix**: Move SDR boost to **after** zone sampling. Linear ops commute with averaging — math is identical.

Before: 1920x1080 x 3 x (linearize + encode + rint) ~ 20M ops
After: 128 x 3 x (linearize + encode + rint) ~ 1K ops

Impact: **~150x fewer pixels**. Also eliminates the Hable tonemap concern for SDR boost.

### Finding: Zone sampling already before Oklch conversion (False Alarm)

Line 413 `zone_colors_array()` returns zone-averaged colors. Line 432 `apply_color_style_mapping()` operates on those. Oklch conversion is already on ~128 zone colors, not full frame.

P2 from the audit was a **false alarm**.

### Finding: Hable LUT caching (Medium Win)

`color/hdr.py:142-160` — Hable curve depends only on `max_nits`. If unchanged, precompute LUT once.

After SDR boost fix, Hable only used for true PQ/HLG input (rare). Low priority.

### Finding: HID round-trips mitigated by caching (Already Done)

usb_driver.py caches `_initialized`, `_cached_on_state`, `_cached_brightness`. First-call overhead is expected. **Accept as-is.**

### Finding: GStreamer caps not cached (Small Win)

`xdg_portal.py:739-744` — `VideoInfo.new_from_caps()` on every sample pull. Cache keyed by caps structure.

### Finding: Legacy D-Bus introspection not cached (Small Win)

`kwin_dbus.py:401-432` — ScreenShot2 path caches, legacy doesn't. Cache `introspect()` result.

---

## Summary: Implementation Plan

### Phase A: Performance (quick wins, ~1 hr)

| Change | Effort | Impact |
|--------|--------|--------|
| Move SDR boost after zone sampling in engine.py / compositor.py | 30 min | **150x fewer pixels** |
| Cache GStreamer caps in xdg_portal.py | 10 min | Low |
| Cache legacy D-Bus introspection in kwin_dbus.py | 10 min | Low |
| Hable tonemap LUT caching in hdr.py | 15 min | Low-Medium |

### Phase B: ICC Profile Support (new feature, ~11 hrs)

| Change | Effort | Impact |
|--------|--------|--------|
| Create `color/primaries.py` with P3 + AdobeRGB matrices | 1 hr | Foundation |
| Create `color/display_gamut.py` with colord detection | 3 hr | Auto-detect gamut |
| Add EDID fallback | 2 hr | Works without colord |
| Extend hdr.py convert_frame_to_srgb8() | 2 hr | Color accuracy |
| Wire gamut into engine.py | 1 hr | Integration |
| Config + UI for gamut override | 2 hr | User control |

### Total: ~12 hours

---

## Freebuff Invocation Snippet

```
@read .opencode/plans/icc-profile-and-performance-research.md

Implement Phase A (performance wins):
1. Move SDR boost compensation from engine.py:403-409 to run AFTER zone sampling in process_frame(). The boost is a linear scalar divide that commutes with averaging. Update compositor.py's apply_sdr_boost_compensation to accept zone colors (n_zones x 3) instead of full frame.
2. Cache GStreamer caps in xdg_portal.py:739-744.
3. Cache legacy D-Bus introspection in kwin_dbus.py:401-432.
4. Add Hable tonemap LUT caching in color/hdr.py:142-160.

Run all verification commands after changes.
```
