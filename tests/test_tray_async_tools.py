from __future__ import annotations

from nanoleaf_sync.tools.output_format import summarize_command_output


def test_summarize_command_output_prefers_combined_preview() -> None:
    preview, rc = summarize_command_output(
        stdout="PASS (3)\nWARN (1)\nAction: rerun doctor\nextra line",
        stderr="",
        returncode=0,
    )
    assert rc == 0
    assert preview.startswith("PASS (3) | WARN (1) | Action: rerun doctor")
    assert "extra line" not in preview


def test_summarize_command_output_uses_stderr_and_default_when_empty() -> None:
    preview_err, rc_err = summarize_command_output(
        stdout="", stderr="permission denied", returncode=2
    )
    assert rc_err == 2
    assert "permission denied" in preview_err

    preview_empty, rc_empty = summarize_command_output(stdout="", stderr="", returncode=0)
    assert rc_empty == 0
    assert preview_empty == "No command output captured."
