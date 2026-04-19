from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserFacingError:
    kind: str
    summary: str
    guidance: str


def translate_runtime_error(error: Exception) -> UserFacingError:
    message = str(error or "Unknown runtime error")
    normalized = message.lower()

    if "unsupported nanoleaf model" in normalized:
        return UserFacingError(
            kind="unsupported-model",
            summary=message,
            guidance=(
                "This app currently supports NL82K1/NL82K2 USB models only. "
                "Use a supported Nanoleaf USB device."
            ),
        )

    if "device not found" in normalized:
        return UserFacingError(
            kind="device-not-found",
            summary=message,
            guidance=(
                "Verify the USB device is connected, powered, and matches configured VID/PID. "
                "Use `nanoleaf-kde-sync-doctor --device` to inspect HID detection."
            ),
        )

    if "failed to open nanoleaf hid device" in normalized or "permission" in normalized:
        return UserFacingError(
            kind="hid-permission",
            summary=message,
            guidance=(
                "Install the provided udev rule, reload udev, reconnect the device, "
                "and confirm your user can access the HID node without sudo."
            ),
        )

    if "screen" in normalized and ("access denied" in normalized or "notauthorized" in normalized):
        return UserFacingError(
            kind="kwin-authorization",
            summary=message,
            guidance=(
                "KWin ScreenShot2 access requires a desktop file with "
                "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2 and a fresh session login."
            ),
        )

    if "kde policy" in normalized and "screenshot" in normalized:
        return UserFacingError(
            kind="kwin-authorization",
            summary=message,
            guidance=(
                "KWin denied screenshot authorization. Launch from an installed desktop entry containing "
                "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2 and re-login to Plasma."
            ),
        )

    if "method/signature is incompatible" in normalized or "invalidargs" in normalized or "unknownmethod" in normalized:
        return UserFacingError(
            kind="kwin-signature-mismatch",
            summary=message,
            guidance=(
                "KWin ScreenShot2 exists but method signatures differ on this Plasma build. "
                "Run `nanoleaf-kde-sync-doctor --capture` and share the detailed output."
            ),
        )

    if "no usable kwin screenshot api" in normalized or "no known kwin screenshot" in normalized:
        return UserFacingError(
            kind="kwin-no-api",
            summary=message,
            guidance=(
                "No working KWin screenshot API variant was found for this session/version. "
                "Check Plasma/KWin version compatibility or switch to mock capture."
            ),
        )

    if "payload decode failed" in normalized or ("decode" in normalized and "kwin" in normalized):
        return UserFacingError(
            kind="kwin-decode",
            summary=message,
            guidance=(
                "KWin returned screenshot data that could not be decoded. "
                "Try different capture dimensions and include doctor capture diagnostics in bug reports."
            ),
        )

    if "session bus" in normalized or "dbus_session_bus_address" in normalized:
        return UserFacingError(
            kind="kwin-session-bus",
            summary=message,
            guidance=(
                "The KDE session bus is unavailable or not exported to this process. "
                "Run from your logged-in Plasma session environment."
            ),
        )

    if "all known kwin screenshot" in normalized:
        return UserFacingError(
            kind="kwin-unavailable",
            summary=message,
            guidance=(
                "KWin screenshot DBus interfaces were not reachable. Confirm you are running in KDE Plasma "
                "with a valid session bus and choose mock capture if needed."
            ),
        )

    return UserFacingError(
        kind="runtime",
        summary=message,
        guidance="Run `nanoleaf-kde-sync-doctor` for targeted diagnostics and setup guidance.",
    )
