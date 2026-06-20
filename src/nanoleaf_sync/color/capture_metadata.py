from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

from nanoleaf_sync.color.hdr import HDRMetadata, Primaries, TransferFn

_log = logging.getLogger(__name__)

ContentMode = Literal["sdr", "hdr", "auto"]
DisplayPresetResolved = Literal["sdr", "hdr"]


@dataclass(frozen=True)
class CaptureMetadata:
    transfer: TransferFn = "srgb"
    primaries: Primaries = "bt709"
    max_nits: float = 1000.0
    source: str = "user preset"
    content_mode: ContentMode = "auto"
    capture_primaries_converted: bool = False
    skip_display_gamut_adaptation: bool = False
    assumption: str = ""

    def to_hdr_metadata(self) -> HDRMetadata:
        return HDRMetadata(
            transfer=self.transfer,
            primaries=self.primaries,
            max_nits=self.max_nits,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "transfer": self.transfer,
            "primaries": self.primaries,
            "max_nits": self.max_nits,
            "source": self.source,
            "content_mode": self.content_mode,
            "capture_primaries_converted": self.capture_primaries_converted,
            "skip_display_gamut_adaptation": self.skip_display_gamut_adaptation,
            "assumption": self.assumption,
        }


@dataclass(frozen=True)
class DisplayPresetResolution:
    preset: DisplayPresetResolved
    hdr_transfer: TransferFn
    hdr_primaries: Primaries
    source: str
    assumption: str = ""


def _normalize_transfer(value: object) -> TransferFn:
    normalized = str(value or "srgb").strip().lower()
    if normalized in {"srgb", "pq", "hlg", "linear", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "srgb"


def _normalize_primaries(value: object) -> Primaries:
    normalized = str(value or "bt709").strip().lower()
    if normalized in {"bt709", "bt2020", "unknown"}:
        return normalized  # type: ignore[return-value]
    return "bt709"


def _plasma_hdr_enabled() -> bool | None:
    try:
        result = subprocess.run(
            ["kreadconfig6", "--file", "kwinrc", "--group", "Compositing", "--key", "HDR"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode != 0:
            return None
        value = (result.stdout or "").strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _plasma_sdr_white_nits() -> float | None:
    try:
        result = subprocess.run(
            [
                "kreadconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Compositing",
                "--key",
                "SDRBrightness",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode != 0:
            return None
        raw = (result.stdout or "").strip()
        if not raw:
            return None
        return float(raw)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def resolve_display_preset(
    *,
    display_preset: str,
    hdr_transfer: str,
    hdr_primaries: str,
    compositor_hdr_mode: bool,
    sdr_boost_nits: float,
) -> DisplayPresetResolution:
    preset = str(display_preset or "hdr").strip().lower()
    if preset != "auto":
        resolved: DisplayPresetResolved = "sdr" if preset == "sdr" else "hdr"
        return DisplayPresetResolution(
            preset=resolved,
            hdr_transfer=_normalize_transfer(hdr_transfer),
            hdr_primaries=_normalize_primaries(hdr_primaries),
            source="user preset",
        )

    hdr_enabled = _plasma_hdr_enabled()
    sdr_nits = _plasma_sdr_white_nits()
    if hdr_enabled is True or compositor_hdr_mode or float(sdr_boost_nits) > 80.0:
        assumption = "Plasma HDR session detected"
        if sdr_nits is not None and sdr_nits > 80.0:
            assumption = f"{assumption}; SDR white reference {sdr_nits:.0f} nits"
        return DisplayPresetResolution(
            preset="hdr",
            hdr_transfer="pq",
            hdr_primaries="bt2020",
            source="plasma auto",
            assumption=assumption,
        )
    if hdr_enabled is False:
        return DisplayPresetResolution(
            preset="sdr",
            hdr_transfer="srgb",
            hdr_primaries="bt709",
            source="plasma auto",
            assumption="Plasma HDR disabled",
        )
    kde_session = os.environ.get("KDE_SESSION_VERSION", "")
    if kde_session:
        return DisplayPresetResolution(
            preset="hdr",
            hdr_transfer=_normalize_transfer(hdr_transfer),
            hdr_primaries=_normalize_primaries(hdr_primaries),
            source="session fallback",
            assumption="Could not read Plasma HDR state; using configured HDR transfer/primaries",
        )
    return DisplayPresetResolution(
        preset="sdr",
        hdr_transfer="srgb",
        hdr_primaries="bt709",
        source="session fallback",
        assumption="Non-KDE session; defaulting to SDR",
    )


def resolve_capture_metadata(
    *,
    backend_metadata: dict[str, Any] | HDRMetadata | None = None,
    user_transfer: str = "srgb",
    user_primaries: str = "bt709",
    user_max_nits: float = 1000.0,
    display_preset: str = "hdr",
    compositor_hdr_mode: bool = False,
    sdr_boost_nits: float = 80.0,
    kwin_display_referred: bool = False,
) -> CaptureMetadata:
    preset_resolution = resolve_display_preset(
        display_preset=display_preset,
        hdr_transfer=user_transfer,
        hdr_primaries=user_primaries,
        compositor_hdr_mode=compositor_hdr_mode,
        sdr_boost_nits=sdr_boost_nits,
    )

    source = "user preset"
    transfer = preset_resolution.hdr_transfer
    primaries = preset_resolution.hdr_primaries
    max_nits = float(user_max_nits)
    assumption = preset_resolution.assumption
    capture_primaries_converted = False
    skip_display_gamut = False

    if backend_metadata is not None:
        if isinstance(backend_metadata, HDRMetadata):
            meta = backend_metadata
        else:
            meta = HDRMetadata.from_any(backend_metadata)
        if isinstance(backend_metadata, dict) and backend_metadata.get("source"):
            source = str(backend_metadata.get("source", "backend"))
        else:
            source = "backend"
        transfer = _normalize_transfer(meta.transfer)
        primaries = _normalize_primaries(meta.primaries)
        max_nits = float(meta.max_nits)
        if primaries == "bt2020":
            capture_primaries_converted = True

    elif kwin_display_referred:
        transfer = "srgb"
        primaries = "bt709"
        source = "kwin display-referred"
        assumption = "KWin screenshot is display-referred sRGB; skipping HDR tone map at capture"

    elif preset_resolution.source == "plasma auto":
        source = preset_resolution.source
        if assumption:
            assumption = assumption

    if capture_primaries_converted and primaries == "bt2020":
        skip_display_gamut = True

    return CaptureMetadata(
        transfer=transfer,
        primaries=primaries,
        max_nits=max_nits,
        source=source,
        content_mode="auto",
        capture_primaries_converted=capture_primaries_converted,
        skip_display_gamut_adaptation=skip_display_gamut,
        assumption=assumption,
    )


def effective_led_profile_key(resolved_preset: DisplayPresetResolved) -> str:
    return "sdr" if resolved_preset == "sdr" else "hdr"
