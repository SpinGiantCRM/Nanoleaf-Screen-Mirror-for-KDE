# Plan: Settings / Menu Revamp (structure only)

## Scope and constraints

This plan is intentionally **structure-only** and preserves all current behavior.

- Keep the current KDE tray app model.
- Keep single-device assumptions (one Nanoleaf Edge Strip only).
- No plugin framework or multi-device UI.
- No feature additions; only reorganize entry points and section grouping.

## Current structure snapshot (baseline)

### Tray menu today

Top-level actions:
- Start / Stop
- Settings
- Setup Wizard
- About / Status
- Troubleshooting / Advanced submenu
- Quit

Troubleshooting / Advanced submenu includes:
- Advanced / Troubleshooting dialog
- Troubleshooting
- Open Troubleshooting Guide
- Run Doctor
- Run Smoke Test
- Reset Auto-Probe Cache
- Show launch diagnostics
- Enable/Disable autostart

### Settings dialogs today

Two modes of the same dialog implementation:
- **Standard view**: Display & Color, Performance, Edge Mapping, Calibration, Device.
- **Advanced view**: Diagnostics section only.

Diagnostics currently mixes together:
- probe policy controls
- latency and xdg-portal probe buttons
- edge locality / colour diagnostics
- self-check
- capture/export report actions
- backend/mapping/HDR detail labels

## Proposed target information architecture

## 1) Tray menu (top-level)

Proposed top-level menu:
1. Start
2. Stop
3. Settings…
4. Calibration…
5. Advanced / Troubleshooting ▶
6. About / Status
7. Quit

Notes:
- Keep Setup Wizard available but move it under **Calibration…** as an in-dialog entry (or secondary action from Calibration window) rather than a top-level daily action.
- Keep all existing troubleshooting actions reachable under **Advanced / Troubleshooting**.
- Do not remove any current capability; only relocate launch points.

### Advanced / Troubleshooting submenu (proposed)

Group by intent:

- **Troubleshoot**
  - Troubleshooting
  - Open Troubleshooting Guide
  - Run Doctor
  - Run Smoke Test
  - Show launch diagnostics

- **Backend / Probe Controls**
  - Open Advanced Settings (Diagnostics page)
  - Reset Auto-Probe Cache

- **System Integration**
  - Enable autostart
  - Disable autostart

## 2) Settings sections (normal path)

Settings should stay focused on routine tuning.

### A. Display & Color
- Display preset, motion preset, color style, edge locality, light spread
- HDR advanced controls (collapsed)
- LED color calibration gains and profile controls

### B. Performance
- Brightness, smoothing, smoothing speed
- FPS target
- sampling quality / performance priority
- capture backend selector (keep, but with helper text that deep probe tools are in Advanced)

### C. Device
- Device model / VID / PID
- output channel order
- start on launch

### D. Mapping
- Screen sampling zone count
- Strip LED zone count
- strip mismatch warnings and apply/keep detected controls

### E. Calibration
- Entry points only:
  - Open calibration tool
  - Re-run setup wizard
  - Reset anchors and recalibrate
- Keep detailed probe/export diagnostics out of this section.

## 3) Advanced / Troubleshooting sections

Create explicit sections within the advanced dialog instead of one large Diagnostics block.

### A. Runtime Status
- Effective backend, selection source/reason
- raw mapping summary
- HDR color-path summary

### B. Backend & Probing
- Auto-probe policy
- latency auto-run policy
- re-test backends, test portal, benchmark portal
- manual latency measurement

### C. Diagnostics Actions
- self-check
- capture one diagnostic frame
- export sampling overlays
- export zone report
- export latency report

### D. Quality Diagnostics
- edge locality diagnostic action/result
- colour accuracy diagnostic action/result

### E. Recovery Tools
- troubleshooting shortcuts (doctor/smoke)
- launch diagnostics view
- probe cache reset

## What moves where

- Keep **daily visual tuning** in Settings (Display/Performance/Mapping/Calibration/Device).
- Move **failure-analysis controls** and **report export tools** to Advanced / Troubleshooting.
- Keep **troubleshooting command launchers** in tray submenu and optionally duplicate in Advanced “Recovery Tools”.
- Keep **setup wizard** tied to calibration flow rather than tray top-level prominence.

## Migration order (small PRs)

1. **PR 1: Menu labels/grouping only**
   - Reorder tray actions and submenu separators/titles.
   - No behavior changes.

2. **PR 2: Settings section renaming/layout extraction**
   - Rename section headers for clarity (e.g., Edge Mapping → Mapping).
   - Split advanced diagnostics UI into explicit subsection builders (still same controls).

3. **PR 3: Action relocation wiring**
   - Move Calibration and Setup Wizard entry points to new locations.
   - Keep compatibility fallbacks (old callbacks still invoked).

4. **PR 4: Docs/tests alignment**
   - Update README/TROUBLESHOOTING terminology and screenshots (if needed).
   - Update structure assertions in tray/settings tests.

5. **PR 5 (optional hardening):**
   - Add regression checks for navigation paths and section focus behavior.

## Risks and regression checks

### Risks
- Users may lose discoverability of Setup Wizard if moved from top-level.
- Existing tests assert literal menu strings/order and may fail during staged renames.
- Initial-section focus paths may break if section IDs are renamed.
- Advanced actions can become harder to find if over-nested.

### Regression checks
- Every current action remains reachable in <=2 clicks from tray.
- Advanced diagnostics launch still opens the correct advanced view and section.
- Existing shortcuts from status/error guidance still reference valid menu labels.
- Calibration preview pause/resume behavior unchanged.

## Tests to add/update

### Update existing tests
- `tests/test_tray_menu_structure.py`
  - expected top-level order and submenu grouping text.
  - preserve checks that diagnostics are grouped, not mixed into daily top-level.

- `tests/test_settings_dialog.py`
  - update expected section names and advanced-view layout assertions.
  - assert routine settings do not embed raw diagnostic exports.

- `tests/test_tray_settings_apply.py`
  - verify Settings + Advanced entry points still apply config identically.

### Add focused tests
- `tests/test_tray_navigation_paths.py` (new)
  - verify each legacy action route still reachable after reorg.

- `tests/test_settings_section_focus.py` (new)
  - verify `initial_section` targets map to renamed sections.

- `tests/test_advanced_sections.py` (new)
  - verify advanced dialog contains Runtime Status / Backend & Probing / Diagnostics Actions / Quality Diagnostics / Recovery Tools group headings.

## Acceptance criteria for the refactor phase

- Functional parity: no diagnostics or calibration capabilities removed.
- Normal settings are visually separated from troubleshooting/probe controls.
- Tray top-level favors daily actions; deep diagnostics live under Advanced.
- No multi-device abstractions introduced.
