# Task: UI Beautification Pass

## Context

Nanoleaf-Screen-Mirror-for-KDE is a PyQt6 system tray app with a `QSystemTrayIcon` context menu (`tray_app.py:419-476`) and a settings dialog (`settings_dialog.py`, 2341 lines). Both have accumulated UX issues: redundant menu items, duplicate navigation paths, zero visual styling (no QSS anywhere), a jarring "view mode" system that hides all sections when opening from Troubleshooting, and a placeholder Calibration section.

## Files to modify

Primary:
- `src/nanoleaf_sync/ui/tray_app.py` — rewrite `_make_menu()`, update handlers
- `src/nanoleaf_sync/ui/settings_dialog.py` — remove view_mode dualism, thicken Calibration section, replace settings section building

Secondary:
- `src/nanoleaf_sync/ui/style.qss` (NEW) — full QSS stylesheet
- `src/nanoleaf_sync/ui/display_configurator.py` — apply same QSS, improve step nav
- `src/nanoleaf_sync/app/__init__.py` (or wherever `QApplication` is created) — load QSS at startup

Reference: `src/nanoleaf_sync/ui/calibration_widget.py` — reusable `SimpleCalibrationWidget` for inline use

## Changes

### 1. Tray Menu Cleanup (`tray_app.py`)

Current menu structure (messy flat + submenu):
```
Start / Stop / Settings… / Calibration / Setup… / Advanced / Troubleshooting (submenu: has "Advanced / Troubleshooting" as first item — redundant) / About / Status / --- / Quit
```

**1a. Remove redundant submenu header item** — `action_advanced_settings` (line 425) is added as the first item inside the submenu on line 456 with identical text "Advanced / Troubleshooting". The submenu itself already bears this label. Clicking the submenu opens it; clicking the redundant item inside opens the same dialog. Remove line 456 (`advanced_menu.addAction(self.action_advanced_settings)`). Keep the action itself in case it's used elsewhere (but check — if not, delete it).

**1b. Merge duplicate Troubleshooting** — `on_troubleshooting` (line 756) and `on_open_advanced_settings` (line 838) both call `self.on_settings(initial_section="Diagnostics", view_mode="advanced")` with the only difference being that `on_open_advanced_settings` also shows a tray notification. Keep `on_open_advanced_settings` (with the notification), delete `on_troubleshooting`, and remove the "Troubleshooting" action from the menu.

**1c. Restructure menu layout**:

```
───
  Start
  Stop
───
  Settings…
  Calibration / Setup…
  About / Status
───
  Advanced (submenu)
    Advanced Settings (was "Advanced / Troubleshooting", now "Advanced Settings")
    Troubleshooting Guide
    ───
    Run Doctor
    Run Smoke Test
    Reset Auto-Probe Cache
    Show Launch Diagnostics
    ───
    Enable Autostart
    Disable Autostart
───
  Quit
```

**1d. Dynamic autostart** — show only the relevant one (Enable if disabled, Disable if enabled). Use `cfg_mgr` or `self.config` to check.

**1e. Add system theme icons** — `QIcon.fromTheme()` on these actions:
- Start: `"media-playback-start"`
- Stop: `"media-playback-stop"`
- Settings: `"preferences-system"`
- Calibration/Setup: `"preferences-desktop-display"`
- About/Status: `"help-about"`
- Quit: `"application-exit"`

### 2. Settings Dialog — Remove View Mode & Diagnostics as a section (`settings_dialog.py`)

**2a. Remove `view_mode`** — The dialog currently supports `SETTINGS_VIEW_STANDARD` (all sections except Diagnostics) and `SETTINGS_VIEW_ADVANCED` (ONLY Diagnostics). This is jarring. Fix:
- Remove `view_mode` parameter from `SettingsDialog.__init__`.
- Always build all sections, including Diagnostics as the last (collapsible) section at the bottom of the scroll.
- Remove the window title distinction (always "nanoleaf-kde-sync Settings").
- Remove `SETTINGS_SECTIONS`, `SETTINGS_VIEW_STANDARD`, `SETTINGS_VIEW_ADVANCED` constants.
- Simplify `focus_section()` — it just scrolls to the section by name.

**2b. Update callers** in `tray_app.py`:
- `on_settings()` — remove `view_mode` parameter.
- `on_open_advanced_settings()` — just call `on_settings(initial_section="Diagnostics")` without view_mode.
- `on_troubleshooting()` — delete this method; redirect to `on_settings(initial_section="Diagnostics")`.

**2c. Remove "Re-run Display Setup" button** from the Settings dialog. This button chain-opens the Display Configurator wizard from inside Settings, which is confusing. The wizard is accessible from the tray menu directly.

### 3. Thicken Calibration Section (`settings_dialog.py`)

**3a. Import `SimpleCalibrationWidget`** from `calibration_widget.py`.

**3b. Replace the placeholder calibration section** — instead of just a help text + "Open calibration tool" button, embed the `SimpleCalibrationWidget` directly. The section should have:
- Short help text heading (2-3 lines)
- The `SimpleCalibrationWidget` (with prev/next zone, 4 corner buttons, reset anchors, reverse checkbox)
- A "Send test pattern" button
- A "Open full calibration wizard" button (for the full DisplayConfigurator)
- The existing "Open calibration tool" behavior maps to opening DisplayConfigurator

**3c. Wire the widget** to `self._state` (CalibrationState) and `self._calibration_sender` just like the wizard does.

### 4. QSS Stylesheet (`style.qss` — NEW)

Create `src/nanoleaf_sync/ui/style.qss` with:

**4a. Palette** — neutral, works on KDE Plasma Breeze Light/Dark:
```css
/* -- KDE Breeze-inspired neutral palette -- */
/* Backgrounds:  #1e1e1e / #2a2a2a (dark), #f5f5f5 / #ffffff (light) */
/* Text:         #e0e0e0 (dark), #31363b (light) */
/* Accent:       #3daee9 (KDE blue) */
/* Surface:      #333333 (dark), #eff0f1 (light) */
/* Borders:      #444444 (dark), #bdc3c7 (light) */
```

**4b. Rules**:
- `QGroupBox`: border: `1px solid palette(mid)`, border-radius: `6px`, margin-top: `14px`, padding: `12px 8px 8px 8px`, font-weight for title
- `QGroupBox::title`: subcontrol-origin: margin, subcontrol-position: top left, padding: `0 8px`
- `QPushButton`: padding: `6px 16px`, border-radius: `4px`, border: `1px solid palette(mid)`, background: palette(button)
- `QPushButton:hover`: background: palette(light)
- `QPushButton:pressed`: background: palette(dark)
- `QSlider::groove:horizontal`: height: `6px`, background: palette(mid), border-radius: `3px`
- `QSlider::handle:horizontal`: width: `16px`, height: `16px`, margin: `-5px 0`, border-radius: `8px`, background: `#3daee9`
- `QSlider::sub-page:horizontal`: background: `#3daee9`, border-radius: `3px`
- `QComboBox`: padding: `4px 8px`, border-radius: `4px`, border: `1px solid palette(mid)`, min-height: `24px`
- `QLabel[heading="true"]`: font-weight: `bold`, font-size: `13px`, padding: `4px 0`, color: `#3daee9`
- `QGroupBox#diagnosticsGroup`: border-color: `#da4453` (red border for diagnostics/recovery)
- `QScrollArea`: border: none

**4c. Dialog headings** — use the `[heading="true"]` property selector. Add `self.setProperty("heading", True)` and re-polish on section heading labels in `_section_heading()`.

**4d. Load QSS at startup** — in the earliest UI initialization point (likely where `QApplication` is created), load and apply:
```python
qss_path = Path(__file__).resolve().parent / "style.qss"
if qss_path.exists():
    app.setStyleSheet(qss_path.read_text())
```

### 5. Setup Wizard Styling (`display_configurator.py`)

**5a. Same QSS** — if QSS is loaded globally, the wizard gets it automatically. Ensure the wizard's group boxes and buttons look consistent with Settings.

**5b. Step indicator** — add a `QLabel` at the top showing current step, e.g., "Step 2/3: Display Preset". Update on step change.

**5c. Style buttons** — the Cancel/Back/Next/Finish buttons should match the Settings dialog styling.

### 6. UI polish touch-ups

**6a. Settings dialog size persistence** — save dialog geometry to config on close, restore on open. If no saved size, default to `860, 760`.

**6b. Menu state refresh** — `_refresh_mode_labels()` already updates the status action text. Also update the Start/Stop enabled states (disable Start when running, disable Stop when not).

## No-Gos

- Do NOT restructure the settings dialog into tabs. Keep the scrollable single-page layout.
- Do NOT move settings between sections (e.g., don't relocate capture backend from Performance to Diagnostics).
- Do NOT change any behavior of the underlying controls (slider ranges, combo values, save/load logic) — purely UI reorganization and styling.
- Do NOT modify tests unless they fail due to renamed/removed parameters.

## Verification

```bash
cd ~/Projects/Nanoleaf-Screen-Mirror-for-KDE
python -m pytest tests/ -q --timeout=30 --timeout-method=thread 2>&1 | tail -20
```

## Freebuff Snippet

```
freebuff task-spec
```

Run from project root: `~/Projects/Nanoleaf-Screen-Mirror-for-KDE/`
