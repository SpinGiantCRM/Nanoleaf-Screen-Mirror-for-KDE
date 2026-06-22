from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import os
import platform
import sys
import webbrowser
from urllib.parse import urlencode

logger = logging.getLogger(__name__)
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nanoleaf_sync.capture.backend_selection import (
    AUTO_BACKEND,
    KMSGRAB_BACKEND,
    KWIN_DBUS_BACKEND,
    XDG_PORTAL_BACKEND,
    normalize_backend_preference,
)
from nanoleaf_sync.capture.factory import (
    auto_probe_effective_state,
    cached_probe_winner_is_viable,
)
from nanoleaf_sync.compat.kde_version import (
    format_version_tuple,
    get_kwin_version,
    get_plasma_version,
)
from nanoleaf_sync.compat.kwin_probe import get_screenshot2_api_version
from nanoleaf_sync.compat.portal_probe import get_portal_version, supports_pipewire_serial
from nanoleaf_sync.compat.version_snapshot import check_for_upgrade, collect_current_versions
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.desktop_entry import (
    RESTRICTED_IFACE_MARKER,
    desktop_entry_has_restricted_marker,
    installed_desktop_entry_candidates,
    source_desktop_template_path,
    user_autostart_path,
)
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.calibration_resolver import resolve_calibration_mapping_from_config
from nanoleaf_sync.runtime.errors import translate_runtime_error
from nanoleaf_sync.runtime.zone_derivation import source_side_counts_from_config

Status = Literal["pass", "warn", "fail"]

_UPSTREAM_ISSUE_URL = "https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/issues/new"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: Status
    message: str
    action: str = ""


from nanoleaf_sync.capture._utils import effective_runtime_zone_count


def _check_python_runtime() -> DoctorCheck:
    version = sys.version.split()[0]
    if sys.version_info < (3, 11):  # noqa: UP036
        return DoctorCheck(
            "python",
            "fail",
            f"Python 3.11+ required; found {version}.",
            "Install Python 3.11 or newer for this project.",
        )
    return DoctorCheck("python", "pass", f"Python {version} detected.")


def _check_dependencies() -> DoctorCheck:
    missing: list[str] = []
    for mod in ("numpy", "PyQt6", "dbus_next", "hid"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return DoctorCheck(
            "dependencies",
            "fail",
            f"Missing Python modules: {', '.join(missing)}.",
            "Install project deps: pip install -e .[test] "
            "(provides hidapi package and `hid` runtime module).",
        )
    return DoctorCheck("dependencies", "pass", "Core Python modules are importable.")


def _check_session_bus() -> DoctorCheck:
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "").strip()
    if not bus:
        return DoctorCheck(
            "session-bus",
            "fail",
            "DBUS_SESSION_BUS_ADDRESS is not set.",
            "Run inside your KDE Plasma user session (not a root shell without session env).",
        )
    return DoctorCheck("session-bus", "pass", "Session DBus address is available.")


async def _probe_kwin_screenshot2() -> DoctorCheck:
    try:
        from dbus_next.aio import MessageBus

        bus = await MessageBus().connect()
        await bus.introspect("org.kde.KWin", "/org/kde/KWin/ScreenShot2")
        return DoctorCheck("kwin-screenshot2", "pass", "KWin ScreenShot2 interface is reachable.")
    except Exception as exc:
        return DoctorCheck(
            "kwin-screenshot2",
            "warn",
            f"ScreenShot2 interface not confirmed: {exc}",
            "If running Plasma, ensure KWin is active and DBus access is available.",
        )


def _run_probe_sync() -> DoctorCheck:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_probe_kwin_screenshot2())

    result: DoctorCheck | None = None
    error: BaseException | None = None

    def _worker() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(_probe_kwin_screenshot2())
        except BaseException as exc:  # pragma: no cover - defensive fallback
            error = exc

    thread = threading.Thread(target=_worker, name="kwin-probe", daemon=True)
    thread.start()
    thread.join()

    if error is not None:
        raise error
    if result is None:  # pragma: no cover - defensive fallback
        raise RuntimeError("KWin screenshot probe did not return a result.")
    return result


def _check_desktop_authorization() -> DoctorCheck:
    autostart = user_autostart_path()
    if autostart.exists():
        if desktop_entry_has_restricted_marker(autostart):
            return DoctorCheck(
                "desktop-authorization",
                "pass",
                f"Autostart desktop entry is authorized ({autostart}).",
            )
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Autostart desktop entry exists but is missing restricted interface marker "
            f"({autostart}).",
            f"Recreate it with `nanoleaf-kde-sync-autostart enable` so it includes "
            f"{RESTRICTED_IFACE_MARKER}.",
        )

    installed_with_marker: list[Path] = []
    installed_without_marker: list[Path] = []
    for candidate in installed_desktop_entry_candidates():
        if not candidate.exists():
            continue
        if desktop_entry_has_restricted_marker(candidate):
            installed_with_marker.append(candidate)
        else:
            installed_without_marker.append(candidate)

    template = source_desktop_template_path()
    template_has_marker = desktop_entry_has_restricted_marker(template)

    if installed_with_marker:
        first = installed_with_marker[0]
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Authorized desktop entry is installed at {first}, but autostart is disabled.",
            "Enable autostart from tray menu or run `nanoleaf-kde-sync-autostart enable`.",
        )
    if installed_without_marker:
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Installed desktop entry is missing restricted interface marker "
            f"({installed_without_marker[0]}).",
            f"Update package desktop entry to include {RESTRICTED_IFACE_MARKER}.",
        )
    if template.exists() and template_has_marker:
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Source desktop template is authorized ({template}), but no installed "
            "desktop entry or autostart file was found.",
            "Install the desktop file with your package manager, then enable autostart.",
        )
    if template.exists():
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Source desktop template is present but missing restricted interface marker "
            f"({template}).",
            f"Add {RESTRICTED_IFACE_MARKER} to the template and reinstall.",
        )
    return DoctorCheck(
        "desktop-authorization",
        "warn",
        "No desktop entry found in autostart, installed applications, or source template.",
        "Install nanoleaf-kde-sync desktop entry, then run `nanoleaf-kde-sync-autostart enable`.",
    )


def _check_hid_enumeration(config: AppConfig) -> DoctorCheck:
    vid = int(config.device_vid)
    pid = int(config.device_pid)
    if vid == 0 or pid == 0:
        return DoctorCheck(
            "hid-device",
            "fail",
            "VID/PID are unset in config.",
            "Set device_vid/device_pid (for Nanoleaf USB: 0x37fa:0x8201 or 0x37fa:0x8202).",
        )

    try:
        import hid

        devices = hid.enumerate(vid, pid)
    except Exception as exc:
        return DoctorCheck(
            "hid-device",
            "fail",
            f"Unable to enumerate HID devices: {exc}",
            "Install/enable hidapi for your environment and confirm device access "
            "permissions, then rerun doctor.",
        )

    if not devices:
        return DoctorCheck(
            "hid-device",
            "fail",
            f"No matching HID device found for VID={vid:#06x} PID={pid:#06x}.",
            "Connect the device and verify IDs with lsusb, then rerun doctor.",
        )

    details: list[str] = []
    module_file = str(getattr(hid, "__file__", "<unknown>") or "<unknown>")
    module_version = str(getattr(hid, "__version__", "<unknown>") or "<unknown>")
    backend_info = f"backend_module={module_file} backend_version={module_version}"
    for idx, dev in enumerate(devices):
        path = dev.get("path")
        if isinstance(path, bytes):
            path = path.decode("utf-8", errors="replace")
        details.append(
            f"#{idx} path={path or '<unknown>'} interface_number={dev.get('interface_number')!r} "
            f"usage_page={dev.get('usage_page')!r} usage={dev.get('usage')!r} "
            f"release_number={dev.get('release_number')!r} bus_type={dev.get('bus_type')!r} "
            f"manufacturer={dev.get('manufacturer_string')!r} "
            f"product={dev.get('product_string')!r} "
            f"serial={dev.get('serial_number')!r}"
        )

    return DoctorCheck(
        "hid-device",
        "pass",
        (
            f"Found {len(devices)} matching HID device(s) for VID={vid:#06x} PID={pid:#06x}. "
            f"{backend_info}. " + " ".join(details)
        ),
    )


def _check_real_device_probe(config: AppConfig) -> DoctorCheck:
    if int(config.device_vid) == 0 or int(config.device_pid) == 0:
        return DoctorCheck(
            "device-probe", "fail", "Cannot probe device because VID/PID are not configured."
        )

    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(vid=int(config.device_vid), pid=int(config.device_pid))
    )
    try:
        driver.initialize()
        detected_zones = getattr(driver, "reported_zone_count", getattr(driver, "zone_count", None))
        configured_zones = int(getattr(config, "device_zone_count", 0) or 0)
        calibration_zones = int(
            getattr(getattr(config, "calibration", None), "device_zone_count", 0) or 0
        )
        effective_zones = effective_runtime_zone_count(
            configured=configured_zones, detected=detected_zones
        )
        return DoctorCheck(
            "device-probe",
            "pass",
            (
                "Device initialized successfully "
                f"(model={driver.model_number}, zones={driver.zone_count}). "
                "Zone diagnostics: "
                f"detected={int(detected_zones or 0) or 'unknown'}, "
                f"configured={configured_zones or 'auto'}, "
                f"effective_runtime={effective_zones or 'unknown'}, "
                f"nested_calibration={calibration_zones or 'auto'}."
            ),
        )
    except Exception as exc:
        lowered = str(exc).lower()
        open_failure_markers = (
            "failed to open nanoleaf hid device after enumeration",
            "attempt results:",
            "open_path(",
            "open(",
        )
        if any(marker in lowered for marker in open_failure_markers):
            action = (
                "Run `nanoleaf-kde-sync-doctor` and inspect hid-device per-path details, "
                "then retry with `--device`. Inspect the per-path open attempt results "
                "(`open_path(...)` / `open(...)`) to distinguish busy-handle vs backend "
                "mismatch vs permission issues."
            )
        else:
            action = (
                "Verify permissions and supported models first. If permissions are already "
                "correct, rerun `nanoleaf-kde-sync-doctor --device` and capture the full "
                "exception text for deeper HID diagnosis."
            )
        return DoctorCheck(
            "device-probe",
            "fail",
            f"Device probe failed: {exc}",
            action,
        )
    finally:
        try:
            driver.close()
        except Exception:
            logger.debug("Failed to close device driver during doctor probe", exc_info=True)


def _check_calibration_completeness(config: AppConfig) -> DoctorCheck:
    source_zone_count = int(
        len(getattr(config, "zones", []) or []) or getattr(config, "device_zone_count", 0) or 0
    )
    snapshot = resolve_calibration_mapping_from_config(
        config=config,
        source_zone_count=max(1, source_zone_count),
        detected_device_zone_count=None,
        source_side_counts=source_side_counts_from_config(config),
    )
    if snapshot.calibration_incomplete:
        return DoctorCheck(
            "calibration",
            "warn",
            snapshot.status_message,
            "Open Settings > Corner calibration, assign all four unique corner anchors, "
            "Save, then start mirroring again.",
        )
    return DoctorCheck(
        "calibration", "pass", "Corner calibration is complete for runtime streaming."
    )


def _check_mode_consistency(config: AppConfig) -> DoctorCheck:
    normalized = _normalized_backend(config)
    valid_backends = {"", AUTO_BACKEND, KWIN_DBUS_BACKEND, XDG_PORTAL_BACKEND, KMSGRAB_BACKEND}
    if not config.use_mock_capture and normalized not in valid_backends:
        return DoctorCheck(
            "mode-consistency",
            "fail",
            "Unsupported real capture backend in config.",
            "Set prefer_backend to 'auto', 'kwin-dbus', 'xdg-portal', or 'kmsgrab', "
            "or enable mock capture.",
        )
    return DoctorCheck("mode-consistency", "pass", "Capture/device mode configuration is coherent.")


def _normalized_backend(config: AppConfig) -> str:
    normalized = normalize_backend_preference(config.prefer_backend)
    return "" if not (config.prefer_backend or "").strip() else normalized


def _check_probe_status(config: AppConfig) -> DoctorCheck:
    normalized = _normalized_backend(config)
    if normalized != AUTO_BACKEND:
        return DoctorCheck(
            "probe-status",
            "pass",
            f"Auto-probe inactive (requested backend={normalized or 'unset'}). "
            "Selection reason=explicit.",
        )

    cached = str(getattr(config, "auto_selected_backend", "") or "").strip()
    signature = str(getattr(config, "auto_probe_signature", "") or "").strip()
    timestamp = str(getattr(config, "auto_probe_timestamp", "") or "").strip()
    policy = str(getattr(config, "auto_probe_policy", "on-change") or "on-change").strip()
    configured_enabled = bool(getattr(config, "auto_probe_enabled", True))
    effective_enabled, effective_reason = auto_probe_effective_state(configured_enabled)

    if cached == "kmsgrab" and not cached_probe_winner_is_viable(cached):
        return DoctorCheck(
            "probe-status",
            "warn",
            (
                f"Auto-probe cached_winner=kmsgrab is stale: kmsgrab bindings are unavailable "
                f"(effective_enabled={effective_enabled} effective_reason={effective_reason})."
            ),
            "Run `nanoleaf-kde-sync-reset diagnostics --stop-runtime` or set "
            '`prefer_backend = "kwin-dbus"` in config.toml.',
        )

    if cached:
        return DoctorCheck(
            "probe-status",
            "pass",
            (
                f"Auto-probe configured_enabled={configured_enabled} policy={policy} "
                f"cached_winner={cached} effective_enabled={effective_enabled} "
                f"effective_reason={effective_reason} selection_reason=cached-probe "
                f"signature={signature or 'none'} timestamp={timestamp or 'none'}."
            ),
        )
    return DoctorCheck(
        "probe-status",
        "warn",
        (
            f"Auto-probe configured_enabled={configured_enabled} "
            f"effective_enabled={effective_enabled} "
            f"effective_reason={effective_reason} policy={policy} has no cached winner yet "
            "(next decision likely fresh-probe/fallback)."
        ),
        "Start service once (or run smoke test) to record backend decision metadata.",
    )


def _check_real_capture_probe(config: AppConfig) -> DoctorCheck:
    from nanoleaf_sync.capture.factory import create_capture_backend

    capture = None
    try:
        capture = create_capture_backend(
            width=64,
            height=36,
            use_mock_capture=False,
            prefer_backend=config.prefer_backend,
            hdr_max_nits=config.hdr_max_nits,
            hdr_transfer=config.hdr_transfer,
            hdr_primaries=config.hdr_primaries,
            auto_probe_enabled=config.auto_probe_enabled,
            cached_probe_winner=config.auto_selected_backend or None,
        )
        frame = capture.capture()
        path = getattr(capture, "last_capture_path", None) or "unknown"
        return DoctorCheck(
            "capture-probe",
            "pass",
            f"Capture probe succeeded via {path} with frame shape={getattr(frame, 'shape', '?')}.",
        )
    except Exception as exc:
        translated = translate_runtime_error(exc)
        return DoctorCheck(
            "capture-probe",
            "fail",
            f"Capture probe failed ({translated.kind}): {translated.summary}",
            translated.guidance,
        )
    finally:
        try:
            close_fn = getattr(capture, "close", None) if capture is not None else None
            if close_fn is not None:
                close_fn()
        except Exception:
            logger.debug("Failed to close capture backend during doctor probe", exc_info=True)


def collect_kde_compatibility_report() -> list[str]:
    plasma = format_version_tuple(get_plasma_version())
    kwin = format_version_tuple(get_kwin_version())
    screenshot2 = get_screenshot2_api_version()
    portal = get_portal_version()
    upgrade = check_for_upgrade()
    changed = upgrade.get("changed") or {}

    lines = [
        "KDE Compatibility:",
        f"  KWin version:    {kwin}",
        f"  Plasma version:  {plasma}",
        f"  ScreenShot2 API: v{screenshot2 or 'unknown'}",
        f"  Portal version:  {portal or 'unknown'}",
        f"  PipeWire serial: {'yes' if supports_pipewire_serial() else 'no'}",
    ]
    if changed:
        lines.append("  Version changes since last run:")
        for key, item in changed.items():
            lines.append(f"    {key}: {item.get('previous')} -> {item.get('current')}")
    else:
        lines.append("  Version changes since last run: none")
    lines.append(
        "  If mirroring fails after a KDE update, run nanoleaf-kde-sync-doctor "
        "and check project releases for a compatibility update."
    )
    return lines


def run_doctor(
    *, include_device_probe: bool = False, include_capture_probe: bool = False
) -> list[DoctorCheck]:
    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.load()
    cfg = validate_config(cfg)
    normalized = _normalized_backend(cfg)

    checks: list[DoctorCheck] = [
        _check_python_runtime(),
        _check_dependencies(),
        _check_session_bus(),
        _check_mode_consistency(cfg),
        _check_calibration_completeness(cfg),
        _check_probe_status(cfg),
        _check_hid_enumeration(cfg),
    ]
    if not cfg.use_mock_capture:
        if normalized in {"", AUTO_BACKEND, KWIN_DBUS_BACKEND, KMSGRAB_BACKEND}:
            checks.append(_run_probe_sync())
            checks.append(_check_desktop_authorization())
        elif normalized == XDG_PORTAL_BACKEND:
            checks.append(
                DoctorCheck(
                    "desktop-authorization",
                    "pass",
                    "Desktop entry authorization check is not required for xdg-portal backend.",
                )
            )
    if include_device_probe:
        checks.append(_check_real_device_probe(cfg))
    if include_capture_probe:
        checks.append(_check_real_capture_probe(cfg))
    return checks


def _build_issue_body(
    report_text: str,
    env_info: dict[str, Any],
    compat_lines: list[str],
) -> str:
    screenshot2 = env_info.get("last_seen_screenshot2_version", "unknown")
    screenshot2_display = f"v{screenshot2}" if screenshot2 != "unknown" else "unknown"
    rows = [
        ("KWin", env_info.get("last_seen_kwin_version", "unknown")),
        ("Plasma", env_info.get("last_seen_kde_plasma_version", "unknown")),
        ("ScreenShot2 API", screenshot2_display),
        ("Portal version", str(env_info.get("last_seen_portal_version", "unknown"))),
        ("Python", env_info.get("last_seen_python_version", "unknown")),
        ("Platform", f"{sys.platform} / {platform.machine()}"),
    ]

    lines = [
        "## Environment",
        "| Key | Value |",
        "|-----|-------|",
    ]
    for key, value in rows:
        lines.append(f"| {key} | {value} |")

    lines.extend(["", "## KDE Compatibility", "```", *compat_lines, "```"])
    lines.extend(
        [
            "",
            "## Doctor Report",
            "<details>",
            "<summary>Full doctor output</summary>",
            "",
            "```",
            report_text,
            "```",
            "",
            "</details>",
            "",
            "## Error Logs",
            "None captured",
        ]
    )
    return "\n".join(lines)


def _build_upstream_issue_url(*, title: str, body: str) -> str:
    return f"{_UPSTREAM_ISSUE_URL}?{urlencode({'title': title, 'body': body})}"


def _open_upstream_issue(checks: list[DoctorCheck]) -> str:
    report_text = format_report(checks)
    compat_lines = collect_kde_compatibility_report()
    env_info = collect_current_versions()
    body = _build_issue_body(report_text, env_info, compat_lines)
    kwin = env_info.get("last_seen_kwin_version", "unknown")
    plasma = env_info.get("last_seen_kde_plasma_version", "unknown")
    title = f"Compatibility issue: {kwin} / Plasma {plasma}"
    url = _build_upstream_issue_url(title=title, body=body)
    print(url)
    webbrowser.open(url)
    return url


def format_report(checks: list[DoctorCheck]) -> str:
    sections: dict[str, list[str]] = {"pass": [], "warn": [], "fail": []}
    for check in checks:
        icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[check.status]  # nosec B105
        line = f"[{icon}] {check.name}: {check.message}"
        if check.action:
            line += f" Action: {check.action}"
        sections[check.status].append(line)

    output: list[str] = []
    output.append("== nanoleaf-kde-sync doctor ==")
    output.extend(collect_kde_compatibility_report())
    for key in ("fail", "warn", "pass"):
        output.append(f"\n{key.upper()} ({len(sections[key])})")
        output.extend(sections[key] or ["- none"])
    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run diagnostics for nanoleaf-kde-sync")
    parser.add_argument(
        "--device", action="store_true", help="Attempt real device initialize/model/zone probe"
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help=(
            "Attempt a capture probe using your configured backend policy "
            "and report exact failure causes"
        ),
    )
    parser.add_argument(
        "--report-upstream",
        action="store_true",
        help="Open a pre-filled GitHub issue with compatibility and doctor diagnostics",
    )
    args = parser.parse_args(argv)

    include_device = args.device or args.report_upstream
    include_capture = args.capture or args.report_upstream
    checks = run_doctor(include_device_probe=include_device, include_capture_probe=include_capture)
    if args.report_upstream:
        _open_upstream_issue(checks)
    print(format_report(checks))
    failures = [c for c in checks if c.status == "fail"]
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
