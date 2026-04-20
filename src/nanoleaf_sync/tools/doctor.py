from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import threading

from typing import Literal

from nanoleaf_sync.capture.backend_selection import (
    AUTO_BACKEND,
    KMSGRAB_BACKEND,
    KWIN_DBUS_BACKEND,
    XDG_PORTAL_BACKEND,
    normalize_backend_preference,
)
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
from nanoleaf_sync.runtime.errors import translate_runtime_error


Status = Literal["pass", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: Status
    message: str
    action: str = ""


def _check_python_runtime() -> DoctorCheck:
    if sys.version_info < (3, 11):
        return DoctorCheck(
            "python",
            "fail",
            f"Python {sys.version.split()[0]} detected.",
            "Use Python 3.11+.",
        )
    return DoctorCheck("python", "pass", f"Python {sys.version.split()[0]} detected.")


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
            "Install project deps: pip install -e .[test] (provides hidapi package and `hid` runtime module).",
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

    thread = threading.Thread(target=_worker, daemon=True)
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
            f"Autostart desktop entry exists but is missing restricted interface marker ({autostart}).",
            f"Recreate it with `nanoleaf-kde-sync-autostart enable` so it includes {RESTRICTED_IFACE_MARKER}.",
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
            f"Installed desktop entry is missing restricted interface marker ({installed_without_marker[0]}).",
            f"Update package desktop entry to include {RESTRICTED_IFACE_MARKER}.",
        )
    if template.exists() and template_has_marker:
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Source desktop template is authorized ({template}), but no installed desktop entry or autostart file was found.",
            "Install the desktop file with your package manager, then enable autostart.",
        )
    if template.exists():
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Source desktop template is present but missing restricted interface marker ({template}).",
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
        import hid  # type: ignore

        devices = hid.enumerate(vid, pid)
    except Exception as exc:
        return DoctorCheck(
            "hid-device",
            "fail",
            f"Unable to enumerate HID devices: {exc}",
            "Install/enable hidapi for your environment and confirm device access permissions, then rerun doctor.",
        )

    if not devices:
        return DoctorCheck(
            "hid-device",
            "fail",
            f"No matching HID device found for VID={vid:#06x} PID={pid:#06x}.",
            "Connect the device and verify IDs with lsusb, then rerun doctor.",
        )

    return DoctorCheck(
        "hid-device",
        "pass",
        f"Found {len(devices)} matching HID device(s) for VID={vid:#06x} PID={pid:#06x}.",
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
        return DoctorCheck(
            "device-probe",
            "pass",
            f"Device initialized successfully (model={driver.model_number}, zones={driver.zone_count}).",
        )
    except Exception as exc:
        return DoctorCheck(
            "device-probe",
            "fail",
            f"Device probe failed: {exc}",
            "Check udev permissions and supported model list (NL82K1/NL82K2).",
        )
    finally:
        try:
            driver.close()
        except Exception:
            pass


def _check_mode_consistency(config: AppConfig) -> DoctorCheck:
    normalized = _normalized_backend(config)
    valid_backends = {"", AUTO_BACKEND, KWIN_DBUS_BACKEND, XDG_PORTAL_BACKEND, KMSGRAB_BACKEND}
    if not config.use_mock_capture and normalized not in valid_backends:
        return DoctorCheck(
            "mode-consistency",
            "fail",
            "Unsupported real capture backend in config.",
            "Set prefer_backend to 'auto', 'kwin-dbus', 'xdg-portal', or 'kmsgrab', or enable mock capture.",
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
            f"Auto-probe inactive (requested backend={normalized or 'unset'}). Selection reason=explicit.",
        )

    cached = str(getattr(config, "auto_selected_backend", "") or "").strip()
    signature = str(getattr(config, "auto_probe_signature", "") or "").strip()
    timestamp = str(getattr(config, "auto_probe_timestamp", "") or "").strip()
    policy = str(getattr(config, "auto_probe_policy", "on-change") or "on-change").strip()
    enabled = bool(getattr(config, "auto_probe_enabled", True))

    if cached:
        return DoctorCheck(
            "probe-status",
            "pass",
            (
                f"Auto-probe enabled={enabled} policy={policy} cached_winner={cached} "
                f"selection_reason=cached-probe signature={signature or 'none'} timestamp={timestamp or 'none'}."
            ),
        )
    return DoctorCheck(
        "probe-status",
        "warn",
        (
            f"Auto-probe enabled={enabled} policy={policy} has no cached winner yet "
            "(next decision likely fresh-probe/fallback)."
        ),
        "Start service once (or run smoke test) to record backend decision metadata.",
    )


def _check_real_capture_probe(config: AppConfig) -> DoctorCheck:
    from nanoleaf_sync.capture.factory import create_capture_backend

    capture = create_capture_backend(
        width=64,
        height=36,
        use_mock_capture=False,
        prefer_backend=config.prefer_backend,
        hdr_max_nits=config.hdr_max_nits,
        hdr_transfer=config.hdr_transfer,
        hdr_primaries=config.hdr_primaries,
    )
    try:
        frame = capture.capture()
        path = getattr(capture, "last_capture_path", None) or "unknown"
        return DoctorCheck(
            "capture-probe",
            "pass",
            f"Real capture probe succeeded via {path} with frame shape={getattr(frame, 'shape', '?')}.",
        )
    except Exception as exc:
        translated = translate_runtime_error(exc)
        return DoctorCheck(
            "capture-probe",
            "fail",
            f"Real capture probe failed ({translated.kind}): {translated.summary}",
            translated.guidance,
        )
    finally:
        try:
            close_fn = getattr(capture, "close", None)
            if close_fn is not None:
                close_fn()
        except Exception:
            pass


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


def format_report(checks: list[DoctorCheck]) -> str:
    sections = {"pass": [], "warn": [], "fail": []}
    for check in checks:
        icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[check.status]
        line = f"[{icon}] {check.name}: {check.message}"
        if check.action:
            line += f" Action: {check.action}"
        sections[check.status].append(line)

    output: list[str] = []
    output.append("== nanoleaf-kde-sync doctor ==")
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
        help="Attempt a real kwin-dbus capture and report the exact root cause on failure",
    )
    args = parser.parse_args(argv)

    checks = run_doctor(include_device_probe=args.device, include_capture_probe=args.capture)
    print(format_report(checks))
    failures = [c for c in checks if c.status == "fail"]
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
