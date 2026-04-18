from __future__ import annotations


def describe_mode(use_mock_capture: bool, use_mock_device: bool, prefer_backend: str) -> tuple[str, str]:
    capture_mode = "Mock capture" if use_mock_capture else f"Capture: {prefer_backend}"
    device_mode = "Mock device" if use_mock_device else "Real USB device"
    return capture_mode, device_mode


def summarize_command_output(stdout: str, stderr: str, returncode: int) -> tuple[str, int]:
    combined = (stdout or "").strip()
    err = (stderr or "").strip()
    if err:
        combined = f"{combined}\n{err}".strip() if combined else err

    if not combined:
        combined = "No command output captured."

    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    preview = " | ".join(lines[:3])[:700]
    return preview, returncode
