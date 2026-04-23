from __future__ import annotations

from nanoleaf_sync.tools import rc_runner


def test_format_markdown_row_uses_status_icons() -> None:
    row = rc_runner.format_markdown_row(
        date_utc="2026-04-20",
        rc_version="v1.2.3-rc1",
        env_id="A1",
        mode="diagnostic",
        doctor_status="pass",
        smoke_status="fail",
        tray_status="N/A",
        tester="@qa",
        notes="notes",
    )

    assert row == (
        "| 2026-04-20 | v1.2.3-rc1 | A1 | diagnostic | ✅ | ❌ | N/A | @qa | notes |"
    )


def test_run_rc_matrix_emits_matrix_ready_row(monkeypatch) -> None:
    fake_results = [
        rc_runner.CommandResult(
            name="config-init",
            args=["nanoleaf-kde-sync-init-config", "--mode", "diagnostic", "--force"],
            status="pass",
            returncode=0,
            summary="ok",
            stdout="",
            stderr="",
        ),
        rc_runner.CommandResult(
            name="doctor",
            args=["nanoleaf-kde-sync-doctor"],
            status="pass",
            returncode=0,
            summary="ok",
            stdout="",
            stderr="",
        ),
        rc_runner.CommandResult(
            name="smoke",
            args=["nanoleaf-kde-sync-smoke-test"],
            status="fail",
            returncode=1,
            summary="fail",
            stdout="",
            stderr="",
        ),
    ]
    monkeypatch.setattr(rc_runner, "build_command_results", lambda mode: fake_results)

    result = rc_runner.run_rc_matrix(
        mode="diagnostic",
        env_id="A1",
        rc_version="v1.2.3-rc1",
        tester="@qa",
        output_format="markdown",
    )

    assert result.doctor_status == "pass"
    assert result.smoke_status == "fail"
    assert "| v1.2.3-rc1 | A1 | diagnostic | ✅ | ❌ | N/A | @qa |" in result.markdown_row


def test_format_markdown_row_uses_unknown_status_fallback_icon() -> None:
    row = rc_runner.format_markdown_row(
        date_utc="2026-04-20",
        rc_version="v1.2.3-rc1",
        env_id="A1",
        mode="diagnostic",
        doctor_status="pass",
        smoke_status="warn",
        tray_status="N/A",
        tester="@qa",
        notes="notes",
    )

    assert "| ✅ | ❓ | N/A |" in row
