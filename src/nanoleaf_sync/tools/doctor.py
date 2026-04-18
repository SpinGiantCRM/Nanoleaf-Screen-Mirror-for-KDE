from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import threading

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str  # pass | warn | fail
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
            "Install package deps: pip install -r docs/requirements.txt && pip install .",
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
    candidates = [
        Path.home() / ".config" / "autostart" / "nanoleaf-kde-sync.desktop",
        Path("docs/nanoleaf-kde-sync.desktop"),
    ]
    marker = "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2"
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if marker in text:
            return DoctorCheck("desktop-authorization", "pass", f"Desktop entry contains restricted interface marker ({path}).")
        return DoctorCheck(
            "desktop-authorization",
            "warn",
            f"Desktop entry found but missing restricted interface marker ({path}).",
            "Add X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2 then re-login.",
        )

    return DoctorCheck(
        "desktop-authorization",
        "warn",
        "No desktop entry found for autostart or docs template.",
        "Install docs/nanoleaf-kde-sync.desktop and include restricted interface marker.",
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

    return DoctorCheck("hid-device", "pass", f"Found {len(devices)} matching HID device(s) for VID={vid:#06x} PID={pid:#06x}.")


def _check_real_device_probe(config: AppConfig) -> DoctorCheck:
    if int(config.device_vid) == 0 or int(config.device_pid) == 0:
        return DoctorCheck("device-probe", "fail", "Cannot probe device because VID/PID are not configured.")

    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(vid=int(config.device_vid), pid=int(config.device_pid)))
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
    normalized = (config.prefer_backend or "").strip().lower()
    valid_backends = {"", "kwin-dbus", "kwin_dbus", "kwin-dbus-screenshot"}
    if not config.use_mock_capture and normalized not in valid_backends:
        return DoctorCheck(
            "mode-consistency",
            "fail",
            "Unsupported real capture backend in config.",
            "Set prefer_backend to 'kwin-dbus' or enable mock capture.",
        )
    return DoctorCheck("mode-consistency", "pass", "Capture/device mode configuration is coherent.")


def run_doctor(*, include_device_probe: bool = False) -> list[DoctorCheck]:
    cfg_mgr = ConfigManager()
    cfg = cfg_mgr.load()
    cfg = validate_config(cfg)

    checks: list[DoctorCheck] = [
        _check_python_runtime(),
        _check_dependencies(),
        _check_session_bus(),
        _run_probe_sync(),
        _check_desktop_authorization(),
        _check_mode_consistency(cfg),
        _check_hid_enumeration(cfg),
    ]
    if include_device_probe:
        checks.append(_check_real_device_probe(cfg))
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
    parser.add_argument("--device", action="store_true", help="Attempt real device initialize/model/zone probe")
    args = parser.parse_args(argv)

    checks = run_doctor(include_device_probe=args.device)
    print(format_report(checks))
    failures = [c for c in checks if c.status == "fail"]
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
