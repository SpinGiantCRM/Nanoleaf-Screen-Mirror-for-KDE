from __future__ import annotations


def describe_mode(
    use_mock_capture: bool,
    prefer_backend: str,
    *,
    service_running: bool,
    device_discovered: bool,
    device_model: str | None = None,
) -> tuple[str, str]:
    capture_mode = "Mock capture" if use_mock_capture else f"Capture: {prefer_backend}"
    if not service_running:
        device_mode = "USB device: not started"
    elif not device_discovered:
        device_mode = "USB device: not connected"
    else:
        model = (device_model or "").strip()
        device_mode = f"USB device: connected ({model})" if model else "USB device: connected"
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
