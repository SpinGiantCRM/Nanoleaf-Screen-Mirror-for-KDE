from __future__ import annotations

from nanoleaf_sync.tools import rc_runner


def test_mode_specific_command_selection_full_real(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    def _fake_config(*, mode: str):
        calls.append(("config", mode == "full-real"))
        return rc_runner.CommandResult("config-init", [], "pass", 0, "ok", "", "")

    def _fake_doctor(*, include_device_probe: bool):
        calls.append(("doctor", include_device_probe))
        return rc_runner.CommandResult("doctor", [], "pass", 0, "ok", "", "")

    def _fake_smoke(*, send_test_frame: bool):
        calls.append(("smoke", send_test_frame))
        return rc_runner.CommandResult("smoke", [], "pass", 0, "ok", "", "")

    monkeypatch.setattr(rc_runner, "_run_config_init", _fake_config)
    monkeypatch.setattr(rc_runner, "_run_doctor_command", _fake_doctor)
    monkeypatch.setattr(rc_runner, "_run_smoke_command", _fake_smoke)

    rc_runner.build_command_results(mode="full-real")

    assert calls == [
        ("config", True),
        ("doctor", True),
        ("smoke", True),
    ]


def test_mode_specific_command_selection_non_real(monkeypatch) -> None:
    doctor_flags: list[bool] = []
    smoke_flags: list[bool] = []

    monkeypatch.setattr(
        rc_runner,
        "_run_config_init",
        lambda *, mode: rc_runner.CommandResult("config-init", [], "pass", 0, mode, "", ""),
    )

    def _fake_doctor(*, include_device_probe: bool):
        doctor_flags.append(include_device_probe)
        return rc_runner.CommandResult("doctor", [], "pass", 0, "ok", "", "")

    def _fake_smoke(*, send_test_frame: bool):
        smoke_flags.append(send_test_frame)
        return rc_runner.CommandResult("smoke", [], "pass", 0, "ok", "", "")

    monkeypatch.setattr(rc_runner, "_run_doctor_command", _fake_doctor)
    monkeypatch.setattr(rc_runner, "_run_smoke_command", _fake_smoke)

    rc_runner.build_command_results(mode="full-mock")
    rc_runner.build_command_results(mode="capture-real")

    assert doctor_flags == [False, False]
    assert smoke_flags == [False, False]


def test_markdown_row_formatting() -> None:
    row = rc_runner.format_markdown_row(
        date_utc="2026-04-18",
        rc_version="v0.3.0-rc2",
        env_id="A1",
        mode="full-real",
        doctor_status="pass",
        smoke_status="fail",
        tray_status="N/A",
        tester="@qa",
        notes="linked logs",
    )

    assert row == (
        "| 2026-04-18 | v0.3.0-rc2 | A1 | full-real | ✅ | ❌ | N/A | @qa | linked logs |"
    )


def test_failure_to_status_mapping() -> None:
    assert rc_runner.map_returncode_to_status(0) == "pass"
    assert rc_runner.map_returncode_to_status(1) == "fail"
    assert rc_runner.map_returncode_to_status(42) == "fail"
    assert rc_runner.map_returncode_to_status(None) == "fail"
    assert rc_runner.map_returncode_to_status(0, not_applicable=True) == "N/A"


def test_run_with_captured_output_handles_none_return() -> None:
    rc, stdout, stderr = rc_runner._run_with_captured_output(lambda: None)
    assert rc == 0
    assert stdout == ""
    assert stderr == ""
