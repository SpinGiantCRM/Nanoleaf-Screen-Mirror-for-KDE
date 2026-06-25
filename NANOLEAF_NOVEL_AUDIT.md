# Codebase Novel Ideas Audit

## 1. Repository Architecture Map

```
┌─────────────────────────────────────────────────────────────────┐
│                     ENTRY POINTS                                │
│  tray_app.py (PyQt6)    service.py (headless daemon)            │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                    SERVICE LAYER                                 │
│  NanoleafSyncService  ─  startup/shutdown orchestration         │
│  RuntimeLifecycle     ─  lifecycle state machine (idle/starting/ │
│                          running/stopping/failed)                │
│  OutputSessionController ─  exclusive LED access guard          │
└───────────────────────┬─────────────────────────────────────────┘
                        │ install_drivers / _run_runtime
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│             3-STAGE PIPELINE (runtime/engine.py)                 │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐         │
│  │ Capture      │ → │ Process      │ → │ HID Writer   │         │
│  │ Worker       │   │ Worker       │   │ (pacing +    │         │
│  │ (D-Bus/      │   │ (colour      │   │  write)      │         │
│  │  Portal/PW)  │   │  pipeline)   │   │              │         │
│  └──────────────┘   └──────────────┘   └──────────────┘         │
│  SPSC ring buf #1     SPSC ring buf #2                           │
│  (cap=4)              (cap=8)                                    │
│                                                                  │
│  + Supervisory loop (reinit checks, black frame detection)       │
│  + FPS Governor (adaptive, EWMA-based)                           │
│  + LatencyProbe (per-stage timing breakdown)                     │
└───────────────────────┬─────────────────────────────────────────┘
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
┌─────────────────┐ ┌──────────┐ ┌──────────────┐
│ CAPTURE BACKENDS│ │ COLOUR   │ │ DEVICE (USB) │
│                 │ │ PIPELINE │ │              │
│ kwin_dbus.py    │ │          │ │ protocol.py  │
│ xdg_portal.py   │ │ hdr.py   │ │ hid_transport│
│ kmsgrab.py      │ │ srgb.py  │ │ usb_driver   │
│ mock_capture.py │ │ blending │ │ send_policy  │
│ auto_probe.py   │ │ primaries│ │              │
│ factory.py      │ │ zones.py │ │              │
└─────────────────┘ └──────────┘ └──────────────┘
```

**Data/control flow**: Config (TOML) → AppConfig dataclass → service → engine threads. Each thread runs independently with synchronized read/writes via ring buffers and threading events. The supervisor loop (main thread) monitors health and triggers reinit.

**Key architectural observations**:
- The 3-stage pipeline is a textbook producer/consumer pattern — correct but with hidden coupling through `RuntimeState` (shared mutable state read/written by all three threads + supervisor + UI polling).
- The smoothing algorithm (`blending.py`) is a hand-tuned fuzzy-control system with ~100 constants and 14 boolean state vectors per zone — by far the most complex single component. It has no formal specification and no individual component tests.
- Backend selection is a heuristic with caching, environment overrides, and config policy — but the fallback path always returns `kwin-dbus` regardless of whether KWin is functional.

---

## 2. Biggest Hidden Problems

### HP-1: The smoothing algorithm is an untestable control surface

**Problem**: `blending.py` (695 lines) contains a hand-tuned adaptive smoothing filter with ~100 threshold constants, 14 per-zone boolean state vectors, Oklab blending for chromatic zones, One-Euro adaptive filter, deadband hysteresis, and scene activity classification. **There are zero tests that verify individual masking behaviors.** The only validation is "does it look right?" — which varies by user, content, and environment.

**Evidence**: 
- 100 named constants (lines 40-97) with enter/exit hysteresis pairs
- `BlendHysteresisState` has 14 `tuple[bool, ...]` fields, each reconstructed every frame
- `adaptive_one_euro_blend` has 3 separate mask systems (scene activity, zone motion, frame-difference masks) that interact non-linearly
- No unit tests exist for `_hyst_lt`, `_hyst_gt`, `_hyst_lte`, `_hyst_gte`, `_scene_activity_hysteresis`, `_oklab_blend_rows`, or any individual mask path in `adaptive_one_euro_blend`

**Why it matters**: A single wrong constant can cause flicker, ghosting, brightness pumping, or hue oscillation. These defects are hard to reproduce deterministically (they depend on frame content) and harder to diagnose. The algorithm has >10^30 possible state combinations — no human can predict all behaviors.

**Root cause**: The algorithm evolved incrementally through "fix flicker" and "reduce ghosting" patches without a formal model or test harness.

**Current risk**: HIGH. The smoothing is the most user-visible quality factor. A regression here immediately degrades the user experience, and there is no automated way to catch it.

**Best fix**: Add property-based tests for each mask function. For example:
- `_hyst_lt(values, enter=10, exit=8, prev=None)` → `values < 10`
- `_hyst_lt(values, enter=10, exit=8, prev=(True, False, True))` → whether values follow hysteresis

**Novel fix**: Replace the hand-tuned constants with a **Bayesian optimization loop**. Record user satisfaction (via thumbs-up/down in UI) and use the correlation between constant values and user ratings to iteratively improve defaults. This turns the "looks right?" problem into a data-driven optimization.

**How to test**: Add `tests/test_blending.py` with:
- `test_hyst_lt_basic` — verify hysteresis masking
- `test_hyst_gt_basic`
- `test_scene_activity_hysteresis_transitions` — ramp through static→low→medium→high
- `test_adaptive_one_euro_no_mask_interference` — verify each mask doesn't accidentally activate
- `test_oklab_blend_achromatic` — neutral colors → no hue shift
- `test_adaptive_one_euro_black_cut` — rapid dark→bright transition
- `test_neighbor_blend_dark_isolation` — dark zones not contaminated by bright neighbors

---

### HP-2: `RuntimeState._lock` gives a false sense of consistency

**Problem**: `RuntimeState` has a `_lock` that is acquired only by *some* methods. `status_snapshot()` locks and returns a dict, but the dict is immediately used outside the lock by the caller (`service.py:284-586` adds 300+ additional fields to the snapshot dict). Threads mutate state while the snapshot is being extended. The "consistent snapshot" guarantee is an illusion.

**Evidence**: 
- `state.py:27`: `_lock` is public (`threading.Lock`)
- `state.py:417-437`: `status_snapshot()` acquires lock, returns dict
- `service.py:284-586`: caller adds `~300` fields to the dict *after* the lock is released
- `engine.py:1136-1139`: process worker reads `state.prev_sent_colors`, `state.prev_smooth_float_colors`, `state.prev_smoothed_colors` under `state._lock` — this is done in the process worker while the HID writer may be updating them in `record_success()` (line 1711-1719, which takes `state._lock`). So *that* part is correct.
- But `clear_smoothing_history()` (state.py:236-250) takes `_lock`, while `reset_for_start()` (state.py:144-234) does **not** take `_lock` despite modifying the same fields.
- `record_frame_brightness()` (state.py:339) takes `_lock` for the black frame counter, but `sync_black_frame_degradation()` (state.py:365) also takes `_lock` for the same data — OK, consistent.
- `record_stale_output_drop()` (state.py:291) takes `_lock`, but `stale_drop_rate_per_second()` (state.py:308) reads `_lock`-protected fields without the lock.

**Why it matters**: Data races on `state.prev_smoothed_colors`, `state.consecutive_errors`, `state.last_error`, etc. cause:
- Wrong error count displayed to user
- Lost smoothing history (ghosting or flicker)
- Incorrect calibration status shown in UI
- Spurious reinit or missing reinit

**Root cause**: `_lock` discipline was added incrementally as bugs were found, not designed upfront.

**Current risk**: MEDIUM. GIL saves most cases, but `list.append`, `list.clear`, and `int` reads have atomicity issues under threaded mutation.

**Best fix**: Make `_lock` private (`__lock`), audit every state access, and add `_assert_locked()` calls where appropriate.

**Novel fix**: Replace `RuntimeState` with a **transactional observer pattern**:
- State mutations go through `with state.transaction() as tx: tx.prev_sent_colors = [...]`
- The transaction captures all changes atomically
- Observers (UI poll, engine thread) see either the old state or the new state, never a mix
- This is how React/Vue/Elm manage state — and it prevents data races without per-field locking

**How to test**: Add `tests/test_runtime_state.py`:
- `test_status_snapshot_consistency_under_threaded_mutation` — 3 threads reading/writing, snapshot fields are internally consistent
- `test_reset_for_start_thread_safe` — reset while threads read
- `test_concurrent_record_error_and_status_snapshot`

---

### HP-3: Smoothing history cleared independently in 5 places, with different criteria

**Problem**: The smoothing history (prev_smoothed_colors, etc.) is cleared in 5 different locations with different triggers:
1. `engine.py:547-551` — `_clear_pipeline_temporal_state()`: called from supervisory loop on reinit, from process worker on capture continuity gap, from `_run_loop_pipeline` on identity change
2. `engine.py:817-822` — in capture worker: when `capture_gap_s > _CAPTURE_CONTINUITY_GAP_S` (0.5s)
3. `engine.py:931` — in process worker: `state.clear_smoothing_history()` when `should_clear_smoothing` (came from recording frame brightness)
4. `engine.py:938` — in process worker: when dimension_signature changes (resolution change)
5. `engine.py:1076-1082` — when metadata_hysteresis detects a transition

These have overlapping conditions. For example, a 0.6s capture gap triggers both (2) and potentially (3) depending on brightness. The `_clear_pipeline_temporal_state` function has 6 parameters, 3 of which are unused (`capture_buf`, `process_buf` are passed but ignored — `del capture_buf, process_buf` at line 546).

**Evidence**: 
- `engine.py:546`: `del capture_buf, process_buf` — parameters are deleted immediately. These were once used but the function body was gutted.
- `engine.py:544-551`: function signature has 5 parameters, but only `state`, `metadata_tracker`, and `from_supervisory` are used.

**Why it matters**: Smoothing history is the temporal memory of the system. Being wrong about *when* to clear it causes:
- **Ghosting** (if not cleared when it should be): a bright object leaves a trail after the screen goes dark
- **Flicker** (if cleared too often): the smoothing never builds up history
- **Startup flash**: wrong initial state after pause/resume

**Root cause**: Multiple developers added clear triggers without understanding the interaction.

**Current risk**: MEDIUM. Ghosting and flicker are the top user complaints for ambilight apps.

**Best fix**: Consolidate into a single `reset_pipeline_state()` function with documented preconditions. Remove unused parameters. Add a reason string for logging.

**Novel fix**: Implement a **smoothing confidence meter** — track how many consecutive frames have been consistent (low motion), and only clear the smoothing history when the confidence drops below a threshold or the frame content unambiguously indicates a scene cut (delta > 5× normal motion). This is how video codecs handle scene change detection — a sudden jump in inter-frame difference signals a scene cut, not camera movement.

**How to test**: Add `tests/test_engine.py`:
- `test_smoothing_clear_triggers_non_overlapping` — verify only one trigger fires per condition
- `test_capture_gap_does_not_clear_when_dimensions_unchanged`
- `test_smoothing_preserved_across_brief_interruptions`
- `test_pipeline_clear_does_not_reference_deleted_params` — catch dead parameter patterns

---

### HP-4: HDR colour path uses a content-heuristic that can silently fail

**Problem**: `analyze_hdr_path()` in `hdr.py:232-281` uses `_looks_sdr_encoded()` (line 256-258) to decide whether the input is "actually HDR" or "looks like SDR". This heuristic uses the 99.5th percentile of pixel values (`np.percentile(rgb, 99.5)`). If a user is watching an HDR movie with a dark scene (99.5th percentile < 0.58 for PQ), the system silently treats it as SDR and bypasses tone mapping — even though the colour primaries and transfer are PQ/BT.2020. The result is washed-out colours during dark HDR scenes.

**Evidence**: `hdr.py:211-217`: `_looks_sdr_encoded` checks `p99 < 0.58` for PQ and `p99 < 0.70` for HLG. This is an undocumented, unconfigurable threshold with no user-facing indication when it fires.

**Why it matters**: HDR content that is mostly dark (space scenes, night scenes) will look wrong with no explanation. The user sees "HDR preset" in settings but gets SDR processing.

**Root cause**: The heuristic exists to handle D-Bus capture backends that tone-map HDR→SDR before delivering the frame. But it also fires on genuine HDR content with low average luminance.

**Current risk**: MEDIUM. Affects all users with HDR displays and dark content.

**Best fix**: 
- Log a warning when `_looks_sdr_encoded` fires: `"HDR metadata says input transfer=%s but content looks SDR (p99=%.3f below threshold %.2f)"`
- Add a config option to force HDR processing regardless of content analysis
- Add exposure of `assumption` to UI diagnostics

**Novel fix**: Instead of a binary SDR/HDR decision, use **adaptive tone mapping** that blends between the two paths based on the frame statistics:
```
alpha = clamp((p99 - threshold_low) / (threshold_high - threshold_low), 0, 1)
final = alpha * hdr_processed + (1 - alpha) * sdr_passthrough
```
This eliminates the hard cut and works correctly for all content. The blending constants can be tuned by users with a "tone mapping strength" slider.

**How to test**: `tests/test_hdr.py`:
- `test_looks_sdr_encoded_dark_hdr_frame` — PQ frame with dark content
- `test_looks_sdr_encoded_thresholds` — verify thresholds
- `test_adaptive_tone_mapping_blend` — smooth transition
- `test_hdr_path_assumption_logged` — verify log output

---

### HP-5: KWin auto-probe fallback ignores portal entirely

**Problem**: `factory.py:196-197`: `_resolve_auto_backend()` hardcodes the fallback to `KWIN_DBUS_BACKEND`. If KWin's ScreenShot2 is unavailable (wrong Plasma version, permission denied, no D-Bus), the auto-probe tries KWin, fails, then returns KWin as the fallback — guaranteeing failure. The portal path is never selected as the auto-backend fallback, only as an explicit user choice.

**Evidence**: 
- `factory.py:196`: `def _resolve_auto_backend() -> str: return KWIN_DBUS_BACKEND`
- `factory.py:248`: `fallback = _resolve_auto_backend()` used unconditionally
- `backend_selection.py:15-19`: `AUTO_PROBE_CANDIDATES` includes portal, but if all candidates fail, fallback is still KWin
- `backend_normalization.py`: explicitly maps unknown backends to auto, which resolves to KWin

**Why it matters**: A user on a system without KWin screenshot (KDE Plasma 5, or a non-KDE Wayland compositor) will get a "KWin D-Bus screenshot failed" error even though portal capture is available. There is no graceful degradation.

**Root cause**: The project targets KDE Plasma 6 with KWin as the primary path. Portal is treated as a fallback/benchmark option, not a first-class alternative.

**Current risk**: HIGH for non-KDE Wayland compositors, LOW for KDE Plasma 6 users.

**Best fix**: Add a "last resort" fallback chain: KWin → portal → kmsgrab → mock. Apply this only when all probe candidates failed.

**Novel fix**: Implement a **capability scoring system** that replaces the binary pass/fail probe:
- Each backend scores 0-100 based on: latency, colour accuracy, permission state, HDR support, CPU cost, authorization prompt frequency
- The system selects the highest-scoring backend, not the first one that passes
- Scoring runs at startup and after display/configuration changes
- This is how Android's Camera2 API selects capture backends — a HAL that measures and ranks

**How to test**: `tests/test_factory_extended.py`:
- `test_auto_probe_fallback_to_portal` — simulate KWin failure, verify portal selected
- `test_all_backends_fail_fallback_to_mock` — graceful degradation
- `test_capability_scoring_ranks_backends` — scoring unit test

---

### HP-6: Portal negotiation creates/destroys event loops with no cleanup path

**Problem**: `xdg_portal.py:162-183` (`_negotiate_portal_sync`) creates a new asyncio event loop, runs `_negotiate_portal()` to completion, then closes the loop. If the portal session is still alive when `_close_portal_session_sync` is called later (e.g., on Stop), it creates a *new* async loop via `asyncio.run()`. This means the portal session's original D-Bus connection (which is bound to a now-closed loop) is orphaned. The code works around this at line 960 by detaching the old bus before closing.

But there's a subtler issue: if `_negotiate_portal` raises an exception mid-way (e.g., SelectSources times out), the portal session handle is already set but the bus connection is leaking. The `_negotiate_portal_sync` method sets `self._portal_bus = bus` at line 191, but if a subsequent step fails, the exception bubbles up without closing the bus.

**Evidence**: `xdg_portal.py:186-337`: successful path exits via `return fd, node_id`. But between line 191 (`bus = await MessageBus(...).connect()`) and line 337, any exception causes `_negotiate_portal_sync` to re-raise without closing the bus. The bus holds a Unix socket to the D-Bus daemon, which leaks file descriptors.

**Why it matters**: Each failed portal negotiation leaks a D-Bus connection (two Unix sockets). Repeated rapid start/stop cycles can exhaust the file descriptor limit (default 1024 on Linux).

**Root cause**: The `_negotiate_portal_sync` method creates a bus but has no `try/finally` to close it on failure.

**Current risk**: LOW for normal use (users don't repeatedly start/stop). MEDIUM for development/debugging.

**Best fix**: Wrap `_negotiate_portal` body in `try/finally` that sets `self._portal_bus = None` after disconnect.

**Novel fix**: Move portal negotiation and streaming to **a single persistent event loop thread** (like KWin does), instead of creating fresh loops per operation. The KWin backend already uses this pattern (`_ensure_background_loop`). The portal backend should match this architecture.

**How to test**: `tests/test_xdg_portal_robustness.py`:
- `test_portal_bus_leak_on_failed_negotiation` — simulate failure, check bus refcount
- `test_portal_repeated_stop_start_fd_count` — verify FD count doesn't grow
- `test_portal_persistent_loop_matches_kwin` — verify shared loop pattern

---

## 3. Novel Ideas Worth Seriously Considering

### N-1: Diff-based HID updates (like video codec P-frames)

**What**: Instead of sending all N zone colors every frame (intra-frame / I-frame), send only zones that changed above a perceptual threshold (predicted-frame / P-frame). Every 60 frames, send a full refresh I-frame to resynchronize.

**Why it's not obvious**: The HID protocol sends per-report colour data. A "partial update" doesn't exist in the protocol — you must write all zone colors each time. BUT: the system tracks "previous sent colors" already (`prev_sent_colors`). By comparing current colors with `prev_sent_colors`, it can skip the HID write for zones where `delta < quantization_threshold`. This is already partially done (quantization hold in `color_processing.py:363-387`), but it still builds and sends the full payload — it just repeats the previous value for held zones. The novel step is to **skip sending held zones entirely** and use a compact encoding that only includes changed zones.

**Why it might work**: For typical desktop usage, 70-90% of zones change imperceptibly between frames (static desktop icons, browser chrome, terminal, etc.). A compact format: `[count_u8, [zone_index_u8, R_u8, G_u8, B_u8] × count]` could reduce HID writes by 5-10× for static content. USB power is saved, CPU time reduced, and USB bus congestion eliminated.

**Risks**:
- Nanoleaf device must hold previous zone state (it does — we're writing per-zone colors that persist until overwritten)
- A missed packet means zones are wrong until the next I-frame → include I-frame every N frames
- Slightly more complex protocol encoding → needs careful testing

**Prototype plan**:
1. Add `_build_partial_payload(changed_zones: list[(int, RGB)])` to `usb_driver.py`
2. Add `_needs_full_refresh` counter, reset after N frames or on missed ACK
3. In `set_zone_colors`, compute diff against `prev_sent_colors`, pick partial or full encoding
4. The partial format uses command variant 0x82 (SET_ZONE_COLORS_PARTIAL) if device supports it, or send full write with unchanged zones set to their current values (same as current behavior but skip HID write if nothing changed)

**Success criteria**: 50% reduction in HID bytes/frame during typical desktop use. Zero visible difference.

---

### N-2: Adaptive FPS via control theory (PID governor)

**What**: Replace the current threshold-based FPS governor with a PID (Proportional-Integral-Derivative) controller. The current governor measures `actual_work_ms` and compares it to `frame_budget_ms`, stepping the target FPS up or down when the ratio exceeds 1.1×. A PID controller would smoothly adjust FPS based on the *error* (frame_budget - actual_work), its *integral* (accumulated lag), and its *derivative* (trend toward overload).

**Why it's not obvious**: The current system is a simple hysteretic threshold. A PID would give smooth, continuous FPS adaptation without the "step" behavior (currently logged as "FPS governor: stepped down 60→55").

**Why it might work**: Control theory is designed for exactly this — maintaining a target metric (latency/output rate) in a noisy environment (OS scheduling jitter, USB timing variance). A well-tuned PID can keep FPS within 1% of the optimal value without oscillation. The current system allows 10% steps which cause perceptible pacing changes.

**Risks**: 
- PID tuning is finicky — wrong coefficients cause oscillation or slow response
- The current approach is simpler and "works well enough"
- Need to verify that the derivative term doesn't amplify noise (use EWMA-smoothed input)

**Prototype plan**:
1. Add `PIDGovernor` class in `runtime/fps_governor.py` 
2. Tune Kp, Ki, Kd from empirical latency traces
3. Compare against current governor in simulation
4. Keep the threshold-based governor as fallback

**Success criteria**: FPS transitions are imperceptible (<1% frame time variation). No oscillation around the target.

---

### N-3: Perceptually-weighted zone importance map

**What**: Not all screen zones are equally important for ambilight. The center of the screen (where the user is looking) has less influence on periphery lighting than the screen edges. Currently, all zones are sampled equally. A "zone importance map" would weight edge zones higher than center zones, and also weight zones near the screen corners higher (where ambilight biases light outward).

**Why it's not obvious**: Standard ambilight projects (HyperHDR, Prismatik) use equal-weighted zones. But the perceptual goal is to extend the screen's ambient light into the room — zones at the screen edge contribute more to this effect than zones in the center. This is a known principle in ambient lighting research (breath of the lighting effect, not screen matching).

**Why it might work**: The zone sampling code (`zones.py`) already supports per-zone weights — `zone_colors_array_with_meta` has `edge_locality` parameter. But this controls the *sampling distribution within a zone* (how much weight on the edge of the zone vs its center), not the *importance of the zone itself*. A zone importance multiplier would let edge zones dominate the averaged colour while center zones blend in less.

**Risks**:
- Adding another config knob increases complexity
- The effect is subtle — may not be noticeable
- Need a good default that doesn't break existing setups

**Prototype plan**:
1. Add `zone_importance: list[float]` to config, default to 1.0 for all zones
2. Scale zone samples by importance before temporal smoothing
3. Expose "edge emphasis" slider in Settings → Advanced that generates a gradient importance map

**Success criteria**: Visible improvement in ambilight effect width. Measurable via user preference testing.

---

### N-4: Device shadow state with proactive resync

**What**: Maintain an in-memory model of what the Nanoleaf device *should* look like (current colors per zone, on/off, brightness). When ACK tracking shows missed responses, the system doesn't just continue sending incremental updates — it detects the divergence and proactively resends the full state.

**Why it's not obvious**: The current system tracks ACK success/failure (`ack_missed_count`, `ack_expected_count`) and degrades the send policy on high miss rates. But it never resends the full state to recover. This is like TCP with a missing retransmit timer — it adapts its strategy but never corrects the data.

**Why it might work**: When USB is under load, individual HID reports may be dropped. The device's zone colors then diverge from what the app thinks they should be. A full state resend (all zones) re-synchronizes the device in one frame. With a small per-zone CRC or timestamp, the recovery could be even more precise — only resend zones whose shadow state doesn't match the expected output.

**Risks**:
- Full state resend uses more USB bandwidth (which caused the problem in the first place)
- Countermeasure: only resend after `missed_acks > threshold`, and limit to 1 recovery frame per second
- Adding state tracking increases complexity

**Prototype plan**:
1. Add `_shadow_zone_colors: list[RGBTuple]` to `NanoleafUSBDriver`
2. Track `shadow_diverged: bool` — set True after missed ACK
3. When diverged, next frame writes all zones (I-frame mode)
4. After successful ACK, clear diverged flag

**Success criteria**: Number of "zombie zones" (zones stuck at wrong color) drops to zero during USB congestion events.

---

### N-5: Zero-copy zone sampling via numpy advanced indexing

**What**: The current zone sampling in `zones.py` loops over zone rectangles per frame, extracting sub-arrays with slicing. For 48 zones on a 4K frame, this means 48 slice operations, each creating a view then computing mean/median. These can be combined into a single advanced-indexing operation using precomputed zone masks.

**Why it's not obvious**: The current code already uses numpy and has an "integral" (optimized) path. But the integral path computes a full integral image (summed-area table) and then samples from it — this is O(width × height) + O(zones) per frame, where the integral image is O(N) even for static zone layouts. A precomputed zone mask as a `bool[H, W, n_zones]` array allows computing all zone means with `frame @ masks / zone_pixel_counts` — one matrix multiply instead of N slices.

**Why it might work**: For 48 zones on a 1920×1080 frame, the integral image requires computing a (1920+1)×(1080+1) array = ~8MB. The matrix-multiply approach requires a 1920×1080×48 bool mask = ~99MB. Memory is worse BUT: the matrix multiply can use BLAS (numpy uses OpenBLAS/MKL), which is GPU-optimized and parallel. For CPU-only, the integral image is faster. The novel insight is: **which approach is faster depends on zone count and frame size, and we should switch between them dynamically**.

**Risks**:
- Large memory for the mask array (99MB at 4K × 48 zones)
- Matrix multiply on CPU may not be faster than precomputed integral image
- Dynamic switching adds complexity

**Prototype plan**:
1. Benchmark both approaches for (frame size, zone count) pairs
2. Add `SamplingEngine` that selects the fastest approach at startup
3. Fall back to integral/legacy for large zone counts or small frames

**Success criteria**: 20%+ reduction in zone sampling time for the most common configuration (1080p, 48 zones).

---

### N-6: Scene-aware profile switching (activity classifier)

**What**: Classify the current screen content into scene types (static desktop, video, game, presentation, dark movie) and auto-switch the colour processing profile. Currently profiles are manually selected (`color_style: ambient/natural/vivid/punchy`). An ML-free classifier using per-frame statistics (motion, brightness variance, chroma distribution, letterbox detection) could predict the content type and adjust smoothing, boost, and spread.

**Why it's not obvious**: The system already has `scene_activity` detection in `blending.py` — but it only affects the smoothing alpha, not the colour style, FPS target, or light spread. A higher-level classifier could switch entire profiles: movies get gentle smoothing + boosted chroma, games get low smoothing + high FPS, static desktop gets aggressive power saving + spread.

**Why it might work**: The statistics needed for classification are already computed every frame (zone delta, brightness, chroma, letterbox). Adding a simple decision tree on top costs <0.01ms per frame.

**Risks**:
- May cause profile oscillation at content boundaries
- User may prefer manual control
- Default should be conservative

**Prototype plan**:
1. Add `SceneClassifier` in `runtime/scene_classifier.py`
2. Features: median zone delta, brightness variance, letterbox margins, chroma variance
3. Simple thresholds: movie = letterbox AND low motion AND low brightness variance
4. Apply profile changes with slow ramp (1-2 second transition)

**Success criteria**: Correct classification for 5 test videos/clips. No oscillation during natural content transitions.

---

### N-7: Frame metering — capture exactly once per compositor frame

**What**: Currently capture fires on a timer. On a 60Hz display with 60FPS capture, most captures land on the same compositor frame (double-sampling the same pixels) — and occasionally on a frame boundary (tearing). Using KWin's frame timing signals (if available) or PipeWire's DMA-BUF buffer-release callback, capture exactly once per new compositor frame. This eliminates double-sampling and tearing.

**Why it's not obvious**: The current system polls at 60Hz. A 60Hz display with 16.67ms refresh means the capture timer fires asynchronously. Sometimes it fires in the first vblank (fine), sometimes in the second (frame repeat), sometimes on the boundary (tearing). Capturing at display refresh rate with phase lock eliminates all three issues.

**Why it might work**: KWin has `org.kde.KWin.FrameGeometry` or similar D-Bus signals. PipeWire delivers buffers with timestamps — the compositor signals when a new frame is available. By waiting for the signal instead of polling, we capture exactly the new frame.

**Risks**:
- Frame timing signal may not exist in all Plasma versions
- Adding D-Bus signal monitoring increases startup complexity
- At high FPS (120+), the signal may arrive faster than the capture pipeline can process

**Prototype plan**:
1. Add `FrameMeter` class that wraps the capture in a wait-for-new-frame pattern
2. For KWin: probe D-Bus for frame-composited signals
3. For portal: use PipeWire buffer timestamps
4. Fall back to timer-based capture when signals unavailable

**Success criteria**: Frame-repeat rate drops from ~30% to <1%. Visual tearing eliminated.

---

## 4. First-Principles Redesign Opportunities

### Opportunity 1: What if the colour pipeline ran in perceptual space exclusively?

**Current**: sRGB → linear → Oklab → processing → linear → sRGB (5 color space conversions per frame per zone)

**First-principles question**: What information does the system actually need? → Perceptual uniformity (human eye response to LED output). sRGB and linear are approximations. Oklab is designed for perceptual uniformity. Why leave it?

**New design**: Store device zone colors **exclusively in Oklab** throughout the pipeline. Capture → zone sample → convert to Oklab → all processing in Oklab → convert to RGB only for the HID write. The smoothing, blending, gain, and calibration all operate on lightness (L), chroma (C), hue (H) — which directly map to perception.

**Benefits**:
- Fewer round-trip conversions (1× Oklab→RGB instead of 2× sRGB→linear + 2× linear→sRGB + 2× Oklab)
- No sRGB→linear→sRGB round-trip errors (gamma quantization)
- LED calibration maps directly to perceptual attributes (lightness ≠ brightness, chroma ≠ saturation)
- Temporal smoothing in Oklab preserves hue consistency (a known problem with RGB smoothing)

**Costs**: Oklab→RGB requires ~3×3 matrix multiply + cube root. Slightly more expensive than RGB lerp, but the pipeline already does this for the "chromatic static" path in blending.py.

### Opportunity 2: What if the capture and processing pipeline were dataflow-driven?

**Current**: Three threads with shared mutable state, event-based wakeup, and manual timer pacing.

**First-principles question**: What is the simplest model for a pipeline with three stages that must run at different rates? → Dataflow graphs. Each stage is a pure function. The wire between them is a bounded queue with backpressure.

**New design**: Model the pipeline as a dataflow graph using Python's `asyncio` channels or a dedicated streaming library. Each stage is a coroutine that reads from an input channel and writes to an output channel. The scheduler decides when to run each stage based on data availability and pacing.

**Benefits**:
- No shared mutable state — each stage is a pure transform
- Natural backpressure — if HID write is slow, the output channel fills up, and the processing stage blocks, which blocks capture
- Deterministic — replaying the same input frames produces the same output
- Testable — stages can be unit tested by feeding in synthetic data and checking output
- No threading bugs

**Costs**: Requires rewriting the engine loop in async style. Python's async overhead (coroutine switching) adds ~1μs per stage, negligible at 60FPS.

### Opportunity 3: What if the system measured its own performance and reported confidence?

**Current**: The status dict has ~100 fields but no single "trust this number" metric.

**First-principles question**: What would make a user trust the app is working? → A single confidence score: "I am 96% confident the lights match the screen."

**New design**: A `MirroringConfidence` score that combines:
- Capture health (frames received / frames expected, %)
- Processing health (mean pipeline latency / frame budget, %)
- Output health (ACK rate, shadow device divergence)
- Smoothing convergence (zone delta EWMA < 5% of full range)

Displayed as a single percentage in the tray tooltip and diagnostics. Below 80%, show recommendations. Below 50%, trigger a self-check.

**Benefits**:
- Single source of truth for "is this working?"
- Actionable diagnostics ("confidence dropped to 60% — check USB cable")
- The score is computed from existing metrics — zero new data, just better presentation

---

## 5. Small High-Leverage Improvements

| Change | What | Why | Effort | Impact |
|--------|------|-----|--------|--------|
| Remove dead params from `_clear_pipeline_temporal_state` | Delete `capture_buf`, `process_buf` params (engine.py:544-546) | Dead code causes confusion | 5 min | Prevents future confusion |
| Add `_assert_locked()` to `reset_for_start()` | Ensure lock is held in `state.py:144` | Prevents race during start | 10 min | Catches a real bug |
| Log `_looks_sdr_encoded` decisions | Add logger.warning in `hdr.py:256-265` | Makes silent HDR decision visible | 10 min | Saves debugging time |
| Add `stale_drop_rate_per_second()` lock | Acquire `_lock` in `state.py:308-313` | Fixes data race on stale drop metrics | 5 min | Correctness |
| Expose `assumption` in diagnostics | Show in `hdr_colour_path` dict (service.py:495) | Users see why HDR/SDR decision was made | 10 min | Transparency |
| Lower `startup_frame_timeout_s` default to 3.0 | config/model.py:227 | 5s is too long to wait for failure | 5 min | Better UX |
| Add `output_channel_order` to `calibration` | Move from top-level config to `CalibrationConfig` | Consistency with other calibration fields | 30 min | Data model hygiene |
| Remove `use_legacy_pipeline` config option | Delete from `config/model.py:224` | Deprecated, always uses 3-stage | 15 min | Cleanup |
| Add `python_version = "3.14"` to mypy config | pyproject.toml:106 | Running on 3.14 | 5 min | Accurate type checking |
| Verify launch desktop file has `X-KDE-DBUS-Restricted-Interfaces` marker | Check docs/nanoleaf-kde-sync.desktop | Required for ScreenShot2 auth | 10 min | Ensures KWin works |

---

## 6. Research Findings

| Source | Finding | How it applies | Novel idea inspired |
|--------|---------|----------------|---------------------|
| HyperHDR source code | Uses PipeWire DMA-BUF with explicit colourimetry negotiation | Confirms `colorimetry=bt709` fix (CI-001) | N-7: Frame metering via PipeWire buffer release callbacks |
| KDE developer blog (Xaver Hugl) | HDR screencast work in progress, not merged | Confirms no HDR capture possible | HP-4: adaptive tone mapping blend (HDR→SDR with smooth fallback) |
| Nanoleaf protocol PDF | No partial update command exists | Diff-based updates must use full writes with unchanged zones | N-1: I-frame/P-frame HID pattern |
| Video codec theory (MPEG) | Scene change detection via inter-frame delta | Apply to smoothing history clearing | HP-3: smoothing confidence meter |
| Control theory (Ziegler-Nichols) | PID tuning for noisy systems | Adaptive FPS governance | N-2: PID FPS governor |
| Android Camera2 HAL | Capability scoring for backend selection | Replace binary pass/fail probe | HP-5: backend scoring system |
| React/Vue state management | Atomic state transitions via immutable snapshots | Thread-safe state management | HP-2: transactional observer pattern |
| Display calibration (ArgyllCMS) | 3×3 colour matrix + per-channel gamma | Validate current calibration approach | N/A — current approach is correct |
| TCP congestion control (AIMD) | Additive increase, multiplicative decrease | Model for FPS governor behavior | N-2: PID is better than AIMD for this use case |
| Blue noise dithering (Bayer matrix) | Temporal dithering for banding reduction | 8-bit LED output quality | Add ordered dither to output quantization |

---

## 7. Ranked Action Plan

| Priority | Problem | Fix | Effort | Risk | Dependencies |
|----------|---------|-----|--------|------|--------------|
| **P0** | HP-6: Portal D-Bus FD leak on failed negotiation | Add try/finally to close bus | 1h | Low | None |
| **P1** | HP-2: RuntimeState lock discipline | Audit and fix `_lock` usage | 2h | Low | None |
| **P1** | HP-4: Silent HDR/SDR misclassification | Log & expose assumption, add force-HDR option | 3h | Low | None |
| **P1** | ~~CI-001: Portal colourimetry~~ | Pin `colorimetry=bt709` in GStreamer | 1h | Low | None |
| **P2** | N-3: Zone importance weighting | Add edge-emphasis multiplier | 4h | Low | Config model change |
| **P2** | HP-5: Auto-probe fallback to portal | Add fallback chain after probe failure | 4h | Medium | May change backend selection logic |
| **P2** | N-1: Diff-based HID updates | Skip unchanged zones in HID write | 8h | Medium | Depends on existing prev_sent tracking |
| **P3** | HP-1: Smoothing algorithm testability | Add property-based tests for each mask | 8h | Low | None |
| **P3** | N-2: PID governor | Replace threshold-based FPS governor | 8h | Medium | Requires tuning on real hardware |
| **P3** | N-6: Scene-aware profiles | Add activity classifier + profile switching | 16h | Medium | New module |
| **Future** | Opportunity 2: Dataflow pipeline | Rewrite engine as asyncio dataflow graph | 40h | High | Full engine rewrite |
| **Future** | N-7: Frame metering | Synchronize capture to compositor frame timing | 20h | High | Depends on KWin/PipeWire signals |

---

## 8. Test and Validation Plan

### Automated tests to add

```
tests/test_blending.py:
  test_hyst_lt_basic                      — hysteresis less-than with prev mask
  test_hyst_gt_basic                      — hysteresis greater-than with prev mask
  test_hyst_lte_basic                     — less-than-or-equal variant
  test_hyst_gte_basic                     — greater-than-or-equal variant
  test_scene_activity_transitions         — static→low→medium→high with hysteresis
  test_adaptive_one_euro_black_cut        — rapid dark→bright transition
  test_adaptive_one_euro_dark_hold        — sustained dark frame
  test_adaptive_one_euro_large_jump       — sudden large zone delta
  test_adaptive_one_euro_hue_oscillation  — alternating hues at same luminance
  test_adaptive_one_euro_motion_presets   — verify calm/responsive/dynamic differ
  test_neighbor_blend_dark_isolation      — dark zone not brightened by neighbor
  test_neighbor_blend_bright_isolation    — bright zone not dimmed by dark neighbor
  test_neighbor_blend_weight_modes        — verify precise/balanced/soft weights
  test_oklab_blend_achromatic_identity    — grey input → grey output
  test_oklab_blend_hue_preservation       — chromatic blend preserves hue
  test_apply_neighbor_blend_stability     — loop stability over 100 frames

tests/test_runtime_state.py:
  test_status_snapshot_consistency        — snapshot fields are internally consistent
  test_record_error_thread_safety         — concurrent record_error calls
  test_reset_for_start_coherence          — all fields reset to defaults
  test_stale_drop_rate_lock               — verify lock held
  test_concurrent_record_and_snapshot     — thread race detection
  test_transactional_state_update         — verify atomic mutations

tests/test_hdr.py:
  test_looks_sdr_encoded_dark_hdr_frame   — PQ frame with low p99
  test_looks_sdr_encoded_bright_sdr_frame — SDR frame with high p99
  test_adaptive_tone_mapping_blend        — smooth blend at threshold boundary
  test_tone_mapping_force_enable          — override ignores content heuristic
  test_hdr_assumption_logged              — assumption written to log

tests/test_factory_extended.py:
  test_auto_probe_fallback_to_portal      — KWin fails, portal selected
  test_all_backends_fail_fallback_to_mock — graceful degradation
  test_capability_scoring_ranks_backends  — scoring function sorts correctly
  test_auto_probe_cache_race              — concurrent create_capture_backend calls

tests/test_xdg_portal_robustness.py:
  test_portal_bus_leak_on_failure         — FD count stable after failed negotiations
  test_portal_repeated_stop_start         — 10 start/stop cycles without error

tests/device/test_hid_transport.py:
  test_diff_based_write_reduced_traffic   — partial updates use fewer bytes
  test_shadow_state_divergence_recovery   — missed ACK triggers full resync
  test_shadow_state_consistency           — shadow matches actual writes
```

### Manual validation commands

```bash
# Verify portal colour consistency
nanoleaf-kde-sync-doctor  # Check colour path diagnostics
# Compare KWin vs portal: capture one frame with each, compare per-zone output

# Verify smoothing quality under various content
nanoleaf-kde-sync-smoke-test  # Basic sync test
# Play: static desktop, video, dark scene, rapid motion, fade transitions

# Verify HDR path decisions
# Set display_preset=hdr, compositor_hdr_mode=True
# Check hdr_colour_path in status for assumption field

# Verify backend selection
# Unset KWin permissions, verify portal auto-fallback
# Set use_mock_capture=True, verify graceful degradation

# Verify FPS governor
# Start with high FPS (120), introduce capture latency, verify governor steps down

# Verify diff-based HID
# Start with static desktop, check HID bytes/frame stays low
```

---

## 9. Final Recommendation

**Do first**: HP-6 (portal FD leak fix, 1h) + HP-2 (RuntimeState lock audit, 2h). These are small, safe, and have been bugs waiting to happen.

**Do next**: Implement diff-based HID updates (N-1, 8h). This is the single highest-impact optimization for this project — it reduces USB traffic, CPU usage, and power consumption with zero user-facing change. The infrastructure (prev_sent tracking) already exists.

**Avoid until needed**: Opportunity 2 (dataflow rewrite, 40h). The current 3-stage pipeline works well. Rewriting it for theoretical purity would take 40h with high risk of introducing new bugs.

**Avoid entirely**: Replacing the smoothing algorithm from scratch. The current algorithm is complex but battleship-tested across thousands of user-hours. Incremental fixes with property-based tests (HP-1) are safer.

**Highest upside novel idea**: N-1 (diff-based HID updates) + N-7 (frame metering) combined — capture exactly once per compositor frame and only send changed zones. This could reduce per-frame overhead by 5-10× on typical content while improving colour accuracy (no double-sampling) and reducing USB congestion.

**If you only do one thing from this audit**: Add `colorimetry=bt709` to the portal GStreamer pipeline (CI-001 from the previous audit). It's a 1-character change to a caps string and is the definitive fix for "portal colours look wrong."
