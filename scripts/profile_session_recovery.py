"""Operator-only fake-session/real-USB recovery regression (no desktop lock).

Requires dbus-next, dbus-daemon and a native bundle plus usb_info operator binary.
Default is plan-only. A private bus deliberately has no capture service: first
exercise capture failure/restoration, then low-brightness exclusive previews,
session interruption and Quit while stopped. Independent controller readback
checks that an earlier restoration was not reused after a later output session.
"""

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from profile_native_lifecycle import control


async def run(args):
    from dbus_next import PropertyAccess
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, dbus_property, method, signal

    class ScreenSaver(ServiceInterface):
        def __init__(self):
            super().__init__("org.freedesktop.ScreenSaver")
            self.active = False

        @method()
        def GetActive(self) -> "b":  # noqa: F821, N802
            return self.active

        @signal()
        def ActiveChanged(self, active: "b") -> "b":  # noqa: F821, N802
            return active

    class Login(ServiceInterface):
        def __init__(self):
            super().__init__("org.freedesktop.login1.Manager")

        @dbus_property(access=PropertyAccess.READ)
        def PreparingForSleep(self) -> "b":  # noqa: F821, N802
            return False

        @signal()
        def PrepareForSleep(self, active: "b") -> "b":  # noqa: F821, N802
            return active

    def read_controller():
        info = json.loads(subprocess.check_output([str(args.usb_info), str(args.config)]))
        return {key: info[key] for key in ["controller_power", "controller_brightness"]}

    async def wait_for(predicate, seconds=6):
        until = time.monotonic() + seconds
        state = None
        while time.monotonic() < until:
            with contextlib.suppress(OSError):
                state = control("status")
                if predicate(state):
                    return state
            await asyncio.sleep(0.02)
        raise RuntimeError(f"Session recovery condition timed out: {state}")

    assert subprocess.run(["pgrep", "-x", "nanoleaf-native"], capture_output=True).returncode == 1
    original = args.config.read_bytes()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    before = read_controller()
    bus_process = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address"], stdout=subprocess.PIPE
    )
    bus = process = None
    results = {}
    try:
        address = bus_process.stdout.readline().decode().strip()
        bus = await MessageBus(bus_address=address).connect()
        saver, login = ScreenSaver(), Login()
        bus.export("/ScreenSaver", saver)
        bus.export("/org/freedesktop/login1", login)
        await bus.request_name("org.freedesktop.ScreenSaver")
        await bus.request_name("org.freedesktop.login1")
        env = os.environ.copy()
        env["DBUS_SESSION_BUS_ADDRESS"] = env["DBUS_SYSTEM_BUS_ADDRESS"] = address
        with (
            (args.output / "probe.json").open("w") as out,
            (args.output / "probe.stderr").open("w") as err,
        ):
            process = subprocess.Popen(
                [str(args.binary), "--stream-live-probe", str(args.config), "30"],
                stdout=out,
                stderr=err,
                env=env,
            )
            try:
                # The real controller was opened/restored before the helper
                # reports the intentionally absent private-bus capture service.
                failed = await wait_for(
                    lambda s: not s["running"] and "Screen sharing stopped" in s["message"]
                )
                assert failed["reconnects"] == 1 and failed["frames"] == 0
                results["capture_failure_stopped"] = True
                control("preview", rgb=[24, 24, 24], zone=7)
                await wait_for(lambda s: s["preview"] and s["frames"] > 0)
                saver.active = True
                saver.ActiveChanged(True)
                locked = await wait_for(lambda s: not s["preview"] and "locked" in s["message"])
                for command in ["start", "preview"]:
                    if command == "preview":
                        control(command, rgb=[24, 24, 24], zone=7)
                    else:
                        control(command)
                    await asyncio.sleep(0.05)
                    current = control("status")
                    assert not current["running"] and not current["preview"]
                    assert current["frames"] == locked["frames"]
                    assert current["reconnects"] == locked["reconnects"]
                results["lock_stopped_preview_and_blocked_start_and_preview"] = True
                saver.active = False
                saver.ActiveChanged(False)
                await wait_for(lambda s: "session ready" in s["message"])
                await asyncio.sleep(0.25)
                assert not control("status")["running"] and not control("status")["preview"]
                results["unlock_requires_explicit_start"] = True
                control("preview", rgb=[24, 24, 24], zone=7)
                await wait_for(lambda s: s["preview"] and s["frames"] > locked["frames"])
                # No prior PrepareForSleep(true): missed pre-suspend signal.
                login.PrepareForSleep(False)
                await wait_for(lambda s: not s["preview"] and not s["running"])
                results["resume_without_prepare_stopped_preview"] = True
                await bus.release_name("org.freedesktop.ScreenSaver")
                await wait_for(lambda s: "monitoring unavailable" in s["message"])
                control("preview", rgb=[24, 24, 24], zone=7)
                await asyncio.sleep(0.1)
                assert not control("status")["preview"]
                await bus.request_name("org.freedesktop.ScreenSaver")
                await wait_for(lambda s: "session ready" in s["message"])
                assert not control("status")["preview"] and not control("status")["running"]
                results["monitor_loss_blocks_output_and_recovery_does_not_restart"] = True
                control("quit")
                until = time.monotonic() + 8
                while process.poll() is None and time.monotonic() < until:
                    await asyncio.sleep(0.02)
                assert process.poll() == 0
            finally:
                if process.poll() is None:
                    with contextlib.suppress(OSError):
                        control("quit")
                    # Keep servicing the fake bus while the actor cleans up.
                    until = time.monotonic() + 10
                    while process.poll() is None and time.monotonic() < until:
                        await asyncio.sleep(0.02)
                    assert process.poll() is not None, "Probe failed to exit after Quit"
        raw = json.loads((args.output / "probe.json").read_text())
        assert raw["controller_power_brightness_restored"]
    finally:
        if bus:
            bus.disconnect()
        bus_process.terminate()
        bus_process.wait(timeout=3)
        if process is not None and process.poll() is None:
            raise RuntimeError("Native probe still running; restoration is unverified")
    after = read_controller()
    results.update(
        controller_readback_matches=before == after,
        initial_brightness_differed_from_test_limit=before["controller_brightness"] != 10,
        config_byte_identical=args.config.read_bytes() == original,
        scope=(
            "Private mocked session bus with real acknowledged low-brightness USB previews. "
            "No actual desktop lock, suspend, capture, unplug or optical verification. "
            "Capture service is deliberately absent; final controller readback is independent."
        ),
        app_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
    )
    (args.output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    assert results["controller_readback_matches"] and results["config_byte_identical"]
    print(json.dumps(results, indent=2))


def main():
    if not __debug__:
        raise RuntimeError("Run without -O: operator safety/evidence assertions are required")
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["binary", "usb-info", "config", "output"]:
        parser.add_argument(f"--{arg}", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        print(
            "Plan only: private session signals, two low-brightness zone previews, "
            "controller restoration/readback. No real desktop lock or suspend."
        )
        return
    args.binary = args.binary.resolve(strict=True)
    args.usb_info = args.usb_info.resolve(strict=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
