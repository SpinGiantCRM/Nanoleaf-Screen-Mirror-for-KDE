from __future__ import annotations

import argparse
import contextlib
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable

from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.tools.doctor import run_doctor
from nanoleaf_sync.tools.output_format import summarize_command_output
from nanoleaf_sync.tools.smoke_test import main as smoke_main

Status = str


@dataclass(frozen=True)
class CommandResult:
    name: str
    args: list[str]
    status: Status
    returncode: int
    summary: str
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RunResult:
    date_utc: str
    rc_version: str
    env_id: str
    mode: str
    tester: str
    output_format: str
    commands: list[CommandResult]
    doctor_status: Status
    smoke_status: Status
    tray_status: Status
    notes: str
    markdown_row: str


def map_returncode_to_status(returncode: int | None, *, not_applicable: bool = False) -> Status:
    if not_applicable:
        return "N/A"
    if returncode == 0:
        return "pass"
    return "fail"


def _run_with_captured_output(func: Callable[[], int | None]) -> tuple[int, str, str]:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            result = func()
            returncode = int(result) if result is not None else 0
    except Exception as exc:  # pragma: no cover - defensive fallback
        stderr_buffer.write(f"Unhandled exception: {exc}")
        returncode = 1

    return returncode, stdout_buffer.getvalue(), stderr_buffer.getvalue()


def _run_doctor_command(*, include_device_probe: bool) -> CommandResult:
    def _execute() -> int:
        checks = run_doctor(include_device_probe=include_device_probe)
        failures = [check for check in checks if check.status == "fail"]
        for check in checks:
            print(f"[{check.status.upper()}] {check.name}: {check.message}")
        return 1 if failures else 0

    args = ["nanoleaf-kde-sync-doctor"]
    if include_device_probe:
        args.append("--device")

    rc, stdout, stderr = _run_with_captured_output(_execute)
    summary, _ = summarize_command_output(stdout, stderr, rc)
    return CommandResult(
        name="doctor",
        args=args,
        status=map_returncode_to_status(rc),
        returncode=rc,
        summary=summary,
        stdout=stdout,
        stderr=stderr,
    )


def _run_smoke_command(*, send_test_frame: bool) -> CommandResult:
    argv: list[str] = []
    args = ["nanoleaf-kde-sync-smoke-test"]
    if send_test_frame:
        argv.append("--send-test-frame")
        args.append("--send-test-frame")

    rc, stdout, stderr = _run_with_captured_output(lambda: smoke_main(argv))
    summary, _ = summarize_command_output(stdout, stderr, rc)
    return CommandResult(
        name="smoke",
        args=args,
        status=map_returncode_to_status(rc),
        returncode=rc,
        summary=summary,
        stdout=stdout,
        stderr=stderr,
    )


def _run_config_init(*, mode: str) -> CommandResult:
    def _execute() -> int:
        mgr = ConfigManager()
        created = mgr.initialize(mode=mode, force=True)
        cfg = mgr.load()
        print(f"config reset ({'created' if created else 'updated'}): {mgr.path}")
        print(f"mode={mode} capture={'mock' if cfg.use_mock_capture else cfg.prefer_backend} device=real-usb")
        return 0

    rc, stdout, stderr = _run_with_captured_output(_execute)
    summary, _ = summarize_command_output(stdout, stderr, rc)
    return CommandResult(
        name="config-init",
        args=["nanoleaf-kde-sync-init-config", "--mode", mode, "--force"],
        status=map_returncode_to_status(rc),
        returncode=rc,
        summary=summary,
        stdout=stdout,
        stderr=stderr,
    )


def build_command_results(*, mode: str) -> list[CommandResult]:
    include_real_checks = mode == "full-real"
    return [
        _run_config_init(mode=mode),
        _run_doctor_command(include_device_probe=include_real_checks),
        _run_smoke_command(send_test_frame=include_real_checks),
    ]


def _status_icon(status: Status) -> str:
    mapping = {"pass": "✅", "fail": "❌", "N/A": "N/A"}
    return mapping.get(status, "❓")


def format_markdown_row(
    *,
    date_utc: str,
    rc_version: str,
    env_id: str,
    mode: str,
    doctor_status: Status,
    smoke_status: Status,
    tray_status: Status,
    tester: str,
    notes: str,
) -> str:
    return (
        f"| {date_utc} | {rc_version} | {env_id} | {mode} | "
        f"{_status_icon(doctor_status)} | {_status_icon(smoke_status)} | {_status_icon(tray_status)} | {tester} | {notes} |"
    )


def run_rc_matrix(*, mode: str, env_id: str, rc_version: str, tester: str, output_format: str) -> RunResult:
    results = build_command_results(mode=mode)

    doctor = next(item for item in results if item.name == "doctor")
    smoke = next(item for item in results if item.name == "smoke")
    tray_status = "N/A"
    notes = "Automated run for config/doctor/smoke; tray lifecycle not automated."
    date_utc = datetime.now(timezone.utc).date().isoformat()

    markdown_row = format_markdown_row(
        date_utc=date_utc,
        rc_version=rc_version,
        env_id=env_id,
        mode=mode,
        doctor_status=doctor.status,
        smoke_status=smoke.status,
        tray_status=tray_status,
        tester=tester,
        notes=notes,
    )

    return RunResult(
        date_utc=date_utc,
        rc_version=rc_version,
        env_id=env_id,
        mode=mode,
        tester=tester,
        output_format=output_format,
        commands=results,
        doctor_status=doctor.status,
        smoke_status=smoke.status,
        tray_status=tray_status,
        notes=notes,
        markdown_row=markdown_row,
    )


def _as_json_payload(result: RunResult) -> dict[str, object]:
    payload = asdict(result)
    payload["commands"] = [asdict(item) for item in result.commands]
    return payload


def _print_markdown(result: RunResult) -> None:
    print("# RC runner summary")
    print()
    print("## Machine-readable status")
    print()
    for item in result.commands:
        print(f"- {item.name}: status={item.status} rc={item.returncode} summary={item.summary}")
    print()
    print("## RC_TEST_MATRIX row")
    print()
    print(result.markdown_row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RC matrix checks and format a docs/RC_TEST_MATRIX.md row")
    parser.add_argument("--mode", required=True, choices=["diagnostic", "full-real"])
    parser.add_argument("--env-id", required=True, choices=["A1", "A2", "C1", "C2"])
    parser.add_argument("--rc-version", required=True, help="Release candidate version, e.g. v0.3.0-rc1")
    parser.add_argument("--tester", required=True, help="Tester handle, e.g. @handle")
    parser.add_argument("--output", default="markdown", choices=["markdown", "json"])
    args = parser.parse_args(argv)

    result = run_rc_matrix(
        mode=args.mode,
        env_id=args.env_id,
        rc_version=args.rc_version,
        tester=args.tester,
        output_format=args.output,
    )

    if args.output == "json":
        print(json.dumps(_as_json_payload(result), indent=2))
    else:
        _print_markdown(result)

    has_failures = any(item.status == "fail" for item in result.commands)
    return 1 if has_failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
