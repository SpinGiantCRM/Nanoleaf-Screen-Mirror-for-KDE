# Pixel Pipeline Audit & Novel Sampling Ideas

## Current Pixel Flow (traced end-to-end)

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. SCREEN (native res, e.g. 3840×2160 @ 60Hz)                       │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ KWin ScreenShot2 / Portal / kmsgrab
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. CAPTURE BACKEND (capture/kwin_dbus.py:366-378)                   │
│    Frame decoded from D-Bus reply → raw uint8 ARGB32 (native res)    │
│                                                                      │
│    if frame.shape != target:                                         │
│        frame = _resize_frame(frame, width=480, height=270)           │
│                                                                      │
│    ↓ _resize_frame → _resize_to_target (capture/_utils.py:56-69)     │
│    ↓ NEAREST-NEIGHBOUR: np.linspace(0, H-1, target_H).astype(int)   │
│    ↓ Each output pixel = 1 source pixel, no averaging, no filtering  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ Pushed to capture ring buffer
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. PROCESS WORKER (runtime/engine.py:890-906)                       │
│    frame = payload.frame  ← already 480×270 at this point            │
│    img_h, img_w, _ = frame.shape                                     │
│                                                                      │
│    Calls process_zone_colors() → zone_colors_array_with_meta()        │
└──────────────────────────┬───────────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. ZONE SAMPLING (runtime/zones.py:496-498, 500-507)                │
│                                                                      │
│    if sample_step > 1:        ← stride subsample (default 1 = skip)  │
│        img = img[::step, ::step, :]                                  │
│                                                                      │
│    _cached_sampling_plan → computes per-zone slice coords            │
│    _zone_means_optimized → integral image on 480×270 frame           │
│      → srgb_u8_to_linear01 → cumsum → zone sums → zone averages     │
│      → linear01_to_srgb_u8 → per-zone RGB tuples                     │
│                                                                      │
│    For edge-weighted zones:                                          │
│      _edge_localized_weights → gaussian × edge-bias weight template  │
│      weighted sum via np.einsum                                       │
└──────────────────────────┬───────────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 5. OUTPUT: 48 RGB tuples per frame → colour pipeline → HID write     │
└──────────────────────────────────────────────────────────────────────┘
```

## Three Information Losses

### Loss 1: Nearest-neighbour downsample (`capture/_utils.py:56-69`)

```python
y_idx = np.linspace(0, frame.shape[0] - 1, target_height).astype(np.intp)
x_idx = np.linspace(0, frame.shape[1] - 1, target_width).astype(np.intp)
return frame[y_idx[:, None], x_idx[None, :], :]
```

This is a regular sampling grid. Each output pixel copies exactly one source pixel. At 3840×2160 → 480×270, **63 out of every 64 source pixels are discarded with zero contribution**. A 2-pixel-wide notification badge has a ~3% chance of any pixel aligning with the grid. If it lands on the grid it dominates its zone; if it misses, it's invisible. Frame-to-frame movement of the grid alignment (due to rounding) causes temporal flicker.

**The cursor test**: A 50×50 cursor at 4K → ~6×6 pixels at 480p. The cursor spans ~6 source lines, each of which is 8 source pixels apart in the NN grid. If the cursor moves 4 pixels at 4K, its grid alignment changes and the cursor may appear in a different zone or disappear entirely.

### Loss 2: Inadequate capture resolution (`capture/dimensions.py:11-12`)

```python
DEFAULT_CAPTURE_WIDTH = 480
DEFAULT_CAPTURE_HEIGHT = 270
```

For a 48-zone edge strip on a 16:9 screen:
- Top/bottom zones: 480/12 = 40px wide × (270 × edge_thickness) ≈ 40×22 = **880 pixels per zone**
- Left/right zones: (270 × edge_thickness) × height = 22×270 = **5,940 pixels per zone**

Each zone average is computed from only 880–5,940 pixels instead of the 90K–2M source pixels it represents. The ratio of significance of any single pixel drops from 1:8M to 1:5K — a 1600× **loss of discrimination** for bright features.

### Loss 3: Stride subsample after resize (`runtime/zones.py:496-498`)

```python
if step > 1:
    img = img[::step, ::step, :]  # step=2 → 75% of pixels discarded
```

At step=2, the 480×270 frame becomes 240×135 — 18K pixels for the entire screen. Each zone gets ~30–200 pixels. The integral image average on 30 pixels is dominated by quantization noise (uint8 → 0-255 for each channel, 30 samples → standard error of mean ≈ 255/√30 ≈ ±47 per channel).

---

## Novel Idea 1: Zone-Area Box Filter (Replace NN entirely)

**Core insight**: We don't need the full frame at any resolution. Each zone is an axis-aligned rectangle at the screen edge. We can compute the exact area-weighted colour of each zone directly from the full-resolution source **without resizing and without a full-frame integral image**.

**How**: For each zone rectangle `(x, y, w, h)` in source coordinates, read the full-resolution pixels in that rectangle and compute a multi-level box-filtered average:

```python
def zone_box_average(frame: np.ndarray, zone: ZoneRect, max_samples: int = 256) -> np.ndarray:
    """Area-weighted zone colour using box-filter mipmap."""
    x, y, w, h = zone
    patch = frame[y:y+h, x:x+w, :3]  # Direct slice from full-res frame
    
    # Compute how much to stride within the zone to hit max_samples
    pixel_count = w * h
    if pixel_count <= max_samples:
        return patch.reshape(-1, 3).mean(axis=0).astype(np.uint8)
    
    step = int(np.sqrt(pixel_count / max_samples))
    step = max(1, step)
    
    # Box-filter each step×step block before sampling
    # Reshape to (h//step, step, w//step, step, 3) → mean over step dims
    h_aligned = (h // step) * step
    w_aligned = (w // step) * step
    patch_aligned = patch[:h_aligned, :w_aligned, :]
    
    # Block-averaged downsampling (anti-aliasing box filter)
    blocks = patch_aligned.reshape(h_aligned // step, step, w_aligned // step, step, 3)
    sampled = blocks.mean(axis=(1, 3))  # (h//step, w//step, 3)
    
    return sampled.reshape(-1, 3).mean(axis=0).astype(np.uint8)
```

**Why this is better than current approach**:
- Every source pixel contributes to exactly one zone (no aliasing)
- The box filter is a proper anti-aliasing downsample (unlike nearest-neighbour)
- Memory: reads only the zone pixels, not the full frame (~265K pixels for 48 zones on 4K vs 8.3M for full frame)
- `max_samples=256` bounds the per-zone cost regardless of zone size

**Cost**: 48 zones × 256 pixels × 3 channels × 1 mean = **38K pixels read per frame**, down from 129K (current 480p) with **infinitely more accurate colours**. Zone area is properly represented.

**Edge cases**:
- A zone that's 1 pixel wide (zone_count > capture_width): falls back to nearest-neighbour (1 pixel) — but this is the correct result for a single-pixel zone
- Very small zones (<256 pixels): reads all pixels, no striding → accurate

### Comparison

| Metric | Current (NN 480p) | Box filter (full-res, 256 max/zone) |
|--------|-------------------|-------------------------------------|
| Aliasing | Severe (nearest-neighbour) | None (area-weighted box filter) |
| Small features | Randomly visible/invisible | Proportionally represented |
| Pixels read per frame | 129,600 (at 480p) | ~38,400 (48×800 avg zone pixels → strided to 256) |
| Memory for zone sampling | 480×270 frame + integral buffer (~0.5MB + ~2MB) | Per-zone slices + 1 temp array (~100KB total) |
| Colour accuracy per zone | Poor (aliasing dominates) | Exact area-weighted mean |
| Implementation | Existing, tested | New function, needs testing |

---

## Novel Idea 2: Variance-Adaptive Zone Resolution

**Problem**: Some frames have mostly uniform content (desktop wallpaper) where 480p is fine. Others have fine detail (games, video). The current fixed resolution doesn't adapt.

**Solution**: Measure per-zone variance in the previous frame. If variance is high across many zones (indicating fine detail), capture at higher resolution. If variance is low, capture at lower resolution.

This doesn't require changing the capture backend resolution (which requires re-initialization). Instead, it adjusts the zone sampling on the same captured frame:

```python
def adaptive_zone_step(frame: np.ndarray, zones: list[ZoneRect], 
                        prev_zone_variance: np.ndarray) -> int:
    """Choose sampling step based on zone content complexity."""
    mean_var = np.mean(prev_zone_variance)
    # high variance = complex content → sample more (smaller step)
    # low variance = uniform → sample less (larger step)
    step = max(1, int(8.0 / (mean_var / 64.0 + 0.5)))
    return min(step, 8)
```

The step controls how many pixels to stride within each zone. Default is step=1 (no stride). For static content, step=8 (every 8th pixel) reduces zone sampling cost by 64× with negligible accuracy loss.

**Current state**: The `sample_step` parameter already exists in `zone_colors_array()`, but it's set from `config.zone_sampling_stride` which is fixed at startup. Making it adaptive requires:
1. Computing per-zone variance in the zone sampling step (free — already have the pixels)
2. Feeding it back to the next frame's sampling decision
3. Writing the adaptive step selection function

---

## Novel Idea 3: Multi-Moment Zone Sampling (not just mean)

**Problem**: The mean colour of a zone is often *visually unrepresentative*. A zone with 90% dark blue sky and 10% bright white clouds averages to a dull medium blue — which doesn't match either the sky or the clouds. The eye notices the clouds more than the uniform sky.

**Current state**: The `vivid_weighted` and `palette_adaptive` modes attempt to address this by weighting bright/saturated pixels higher. But they still produce a single average, just with different weights.

**Better approach**: Compute **three statistics per zone** and use a rule-based selector:

```python
def multi_moment_zone(frame_slice: np.ndarray) -> np.ndarray:
    """Return the most representative zone colour using multiple moments."""
    pixels = frame_slice.reshape(-1, 3).astype(np.float32)
    
    # Mean
    mean_rgb = pixels.mean(axis=0)
    
    # Median (robust to outliers)
    median_rgb = np.median(pixels, axis=0)
    
    # Mode (most common colour) via histogram
    # Bin each channel into 16 bins, find peak
    bin_centers = np.arange(0, 256, 16) + 8
    r_hist = np.histogram(pixels[:, 0], bins=16, range=(0, 256))[0]
    g_hist = np.histogram(pixels[:, 1], bins=16, range=(0, 256))[0]
    b_hist = np.histogram(pixels[:, 2], bins=16, range=(0, 256))[0]
    mode_rgb = np.array([
        bin_centers[np.argmax(r_hist)],
        bin_centers[np.argmax(g_hist)],
        bin_centers[np.argmax(b_hist)],
    ])
    
    # Dominant colour via k-means-like binning (fast: quantize to 8×8×8 cube)
    quantized = (pixels // 32).astype(int)
    quant_rgb = quantized[:, 0] * 64 + quantized[:, 1] * 8 + quantized[:, 2]
    dominant_bin = np.bincount(quant_rgb, minlength=512).argmax()
    dominant_rgb = np.array([
        (dominant_bin // 64) * 32 + 16,
        ((dominant_bin // 8) % 8) * 32 + 16,
        (dominant_bin % 8) * 32 + 16,
    ])
    
    # Rule: choose dominant if zone is mixed-content, else mean
    variance = float(np.var(pixels.astype(np.float32), axis=0).mean())
    if variance > 1000:  # High-variance → mixed content → use dominant
        return dominant_rgb.astype(np.uint8)
    return mean_rgb.astype(np.uint8)
```

This is the perceptual insight: for low-variance zones (uniform colour), mean is correct. For high-variance zones (mixed content like text on background), the dominant colour bin gives a more representative ambient colour. The `palette_adaptive` mode already does something related but more complex — the insight here is that simpler methods (quantization binning) achieve the same result with less complexity.

---

## Novel Idea 4: Edge-Anchored Sub-Pixel Sampling

**Problem**: Edge zones are thin rectangles flush against the screen edge. The most important pixels for ambilight are the ones *right at the edge* — they're what the eye sees as the screen's boundary colour. Current weighted sampling (`_edge_localized_weights`) uses a gaussian that emphasises edge pixels, but only within the zone rectangle — which doesn't extend past the screen edge.

**Solution**: For edge zones, extend the zone rectangle slightly *past* the screen edge (into the bezel area, which is always black = zero contribution) to ensure the edge pixels are centre-weighted in the sampling window. Then apply a sharply decaying weight:

```python
def edge_anchored_zone(source_rect: ZoneRect, screen_w: int, screen_h: int) -> ZoneRect:
    """Extend zone past screen edge so the physical edge is centred in the sample."""
    x, y, w, h = source_rect
    padding = max(1, w // 2, h // 2)  # Extend by half the zone thickness
    
    if x == 0:   # Left edge: extend left by padding
        x = max(0, x - padding)
        w = min(screen_w - x, w + padding)
    elif x + w >= screen_w:  # Right edge
        w = min(screen_w - x + padding, screen_w)
    if y == 0:   # Top edge
        y = max(0, y - padding)
        h = min(screen_h - y, h + padding)
    elif y + h >= screen_h:  # Bottom edge
        h = min(screen_h - y + padding, screen_h)
    
    return (x, y, w, h)
```

Then apply a linear edge-decay weight that peaks at the physical screen edge and falls off into the zone interior. This gives maximum weight to the literal screen boundary where ambient light matters most.

The weight function (replacing `_edge_weight_template`):
```python
def edge_anchor_weights(zone_h, zone_w, orientation):
    """Weight that peaks at the screen edge and falls off linearly."""
    yy, xx = np.indices((zone_h, zone_w), dtype=np.float32)
    if orientation == 'top':
        dist = yy  # distance from screen edge (top of zone)
    elif orientation == 'bottom':
        dist = zone_h - 1 - yy
    elif orientation == 'left':
        dist = xx
    else:  # right
        dist = zone_w - 1 - xx
    
    # Exponential decay from edge: weight = exp(-dist / sigma)
    sigma = max(1.0, zone_h * 0.15 if orientation in ('top', 'bottom') else zone_w * 0.15)
    weights = np.exp(-dist / sigma)
    return weights / weights.sum()
```

---

## Novel Idea 5: Temporal Super-Sampling (Frame Accumulation)

**Problem**: Each frame's zone colours are noisy due to the tiny sampling area (50 pixels per zone at 480p). The temporal smoothing (`blending.py`) filters this noise in output space, but doing it in *sampling space* would be more effective.

**Solution**: Maintain a running zone-colour buffer that accumulates a weighted average across frames. For static content, accumulate all frames (reducing noise as √N). For dynamic content, reset accumulation to track the new content:

```python
class ZoneAccumulator:
    """Exponentially-weighted temporal accumulation of zone samples."""
    
    def __init__(self, zone_count: int, alpha_static: float = 0.05, alpha_dynamic: float = 0.5):
        self.accumulated = np.zeros((zone_count, 3), dtype=np.float64)
        self.alpha = alpha_static
        self.alpha_static = alpha_static
        self.alpha_dynamic = alpha_dynamic
    
    def update(self, zone_colors: np.ndarray, frame_delta: float) -> np.ndarray:
        """Accumulate zone colours with adaptive rate based on frame motion."""
        # frame_delta ≈ 0 for static, higher for motion
        self.alpha = self.alpha_static + (self.alpha_dynamic - self.alpha_static) * min(frame_delta, 1.0)
        
        # EMA update
        self.accumulated = (1 - self.alpha) * self.accumulated + self.alpha * zone_colors.astype(np.float64)
        
        return np.clip(np.rint(self.accumulated), 0, 255).astype(np.uint8)
```

This smooths sampling noise before it enters the pipeline. The temporal smoothing in `blending.py` then smooths *output* noise. The two levels of smoothing operate at different timescales: sampling accumulation at ~0.5-5s, output smoothing at ~0.05-0.5s.

---

## Novel Idea 6: Adaptive Zone Count (Not Fixed to Strip Zones)

**Problem**: The LED strip has 48 physical LEDs but the screen may have areas with much finer colour detail. A full-screen gradient uses 48 zones well. A complex game UI with many coloured elements would benefit from more zones, which would then be averaged down to 48 for the strip.

**Solution**: Sample at a higher virtual zone count (e.g., 96 or 192), then cluster or interpolate down to the physical 48. The virtual zones capture more spatial detail, and the down-projection to 48 LEDs preserves more information than sampling 48 zones directly.

```python
def sample_virtual_zones(frame: np.ndarray, virtual_count: int) -> np.ndarray:
    """Sample a regular grid of virtual zones across the full frame width."""
    zone_w = frame.shape[1] / virtual_count
    zone_h = frame.shape[0]
    colors = np.zeros((virtual_count, 3), dtype=np.uint8)
    for i in range(virtual_count):
        x = int(i * zone_w)
        w = int(zone_w)
        patch = frame[:, x:x+w, :3]
        colors[i] = patch.reshape(-1, 3).mean(axis=0)
    return colors

def project_to_strip(virtual_colors: np.ndarray, mapping: np.ndarray) -> np.ndarray:
    """Weighted interpolation from virtual to physical zones."""
    # mapping: (physical_zone_count, virtual_zone_count) weight matrix
    return (virtual_colors.astype(np.float32) @ mapping.T).astype(np.uint8)
```

The `mapping` matrix encodes which virtual zones each physical LED maps to, with bilinear interpolation weights. This is equivalent to sampling at a higher rate and then low-pass filtering — which is exactly what anti-aliasing is. The structure is a **polyphase resampling filter**.

---

## Novel Idea 7: Direct-Pixel Zone Sampling via DMA-BUF (kmsgrab only)

**Problem**: The current kmsgrab backend (`capture/kmsgrab.py`) already operates on DRM framebuffers via DMA-BUF. It has direct GPU memory access. However, after capture, it still goes through the same CPU-based zone sampling path.

**Solution**: For the kmsgrab path, compute zone averages directly on the GPU via a compute shader. The `_drm_zone_sampler.py` already does something zone-related — read it for exact capabilities.

```python
# Hypothetical GPU compute path
def gpu_zone_colors(dma_buf_fd: int, zones: list[ZoneRect]) -> np.ndarray:
    """Use GPU compute to average zones directly on the DMA-BUF."""
    # Map DMA-BUF as Vulkan/OpenCL buffer
    # Launch compute shader that sums pixel values per zone
    # Read back only zone averages (~48×3 bytes)
    # Total data transfer: 144 bytes instead of 24MB
```

This reduces CPU→GPU→CPU data transfer from 24MB/frame (full frame) to 144 bytes/frame (zone colours). The compute shader cost is negligible (48 zone averages on a GPU takes microseconds).

**Caveat**: This requires Vulkan or OpenCL compute on the same GPU that owns the DMA-BUF. The `_drm_helper.c` indicates C-level GPU interaction — but this is a significant engineering effort.

---

## Implementation Roadmap

| Priority | Change | What it does | Effort | Risk | Pixel quality gain |
|----------|--------|-------------|--------|------|-------------------|
| **P0** | Replace NN downsample with box-filter per zone (Idea 1) | Eliminates aliasing, proper area weighting | 2 days | Medium | Massive (fixes flicker) |
| **P1** | Add variance-adaptive zone step (Idea 2) | Dynamic resolution based on content complexity | 1 day | Low | Medium |
| **P2** | Add multi-moment zone colour (Idea 3) | Better zone colour for mixed content | 2 days | Low | Medium |
| **P2** | Edge-anchored zone rects (Idea 4) | More accurate edge colour weighting | 1 day | Low | Small |
| **P3** | Temporal super-sampling (Idea 5) | Reduce sampling noise before pipeline | 2 days | Low | Medium (cumulative) |
| **P3** | Virtual zone oversampling (Idea 6) | Anti-aliased zone sampling via oversampling | 2 days | Medium | Medium |
| **Future** | GPU compute zone sampling (Idea 7) | Zero-copy zone averages on kmsgrab | 2 weeks | High | Large (bandwidth) |

## Concrete Test Plan

```python
# tests/test_zone_sampling_quality.py:
def test_box_filter_vs_nn_color_accuracy():
    """Box filter produces colours within ΔE < 5 of ground truth."""
    
def test_box_filter_no_alias_flicker():
    """Shifting the frame by 1px changes zone colours by < 2%."""
    
def test_variance_adaptive_step_preserves_detail():
    """High-variance zones get step=1, low-variance zones get step>=4."""
    
def test_multi_moment_mixed_content():
    """Zone with 90/10 split selects dominant colour, not washed average."""
    
def test_edge_anchored_zone_weights_peak_at_edge():
    """Weight peaks at the physical screen edge."""
    
def test_temporal_super_sampling_noise_reduction():
    """Static zone colour variance decreases as 1/√N with accumulation."""
```

## Files that would change

| File | Change |
|------|--------|
| `capture/_utils.py` | Add `_box_filter_zone_average()` — replace nearest-neighbour per-zone |
| `runtime/zones.py` | Add `zone_colors_array_adaptive()` — variance-adaptive, multi-moment |
| `runtime/zones.py` | Add `_multi_moment_zone_color()` — mean/median/dominant selector |
| `runtime/zones.py` | Add `edge_anchored_zone()` — rect extension for edge weighting |
| `runtime/zone_accumulator.py` | NEW: `ZoneAccumulator` class for temporal super-sampling |
| `runtime/engine.py` | Wire ZoneAccumulator into process worker |
| `capture/kwin_dbus.py` | Remove (or make optional) the resize-to-480p step when using direct zone sampling |
| `tests/test_zone_sampling_quality.py` | NEW: quality tests for each sampling method |
