from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.runtime.color_processing import color_pipeline_diagnostics

GOLDEN_SWATCH_SAMPLES: dict[str, tuple[int, int, int]] = {
    "grey_16": (16, 16, 16),
    "grey_64": (64, 64, 64),
    "grey_128": (128, 128, 128),
    "grey_196": (196, 196, 196),
    "white": (255, 255, 255),
    "red": (220, 50, 45),
    "green": (40, 210, 90),
    "blue": (45, 95, 225),
    "cyan": (64, 225, 225),
    "magenta": (220, 80, 220),
    "yellow": (240, 225, 80),
    "grey_blue_low_sat": (92, 106, 116),
    "skin_orange": (196, 136, 92),
}


def validate_golden_swatch_bounds(entries: list[dict[str, object]]) -> list[str]:
    violations: list[str] = []
    for entry in entries:
        name = str(entry.get("name", ""))
        out_rgb = entry.get("output_rgb")
        if not isinstance(out_rgb, tuple) or len(out_rgb) != 3:
            continue
        r, g, b = (int(out_rgb[0]), int(out_rgb[1]), int(out_rgb[2]))
        channel_spread = max(r, g, b) - min(r, g, b)
        hue_delta = abs(float(entry.get("hue_difference_degrees", 0.0)))
        chroma_ratio = float(entry.get("chroma_ratio", 1.0))
        l_out = float(entry.get("output_lightness", 0.0))
        l_in = float(entry.get("input_lightness", 0.0))
        l_delta = abs(l_out - l_in)

        if name in {"grey_16", "grey_64", "grey_128", "grey_196", "white"}:
            if not bool(entry.get("neutral_grey_preserved", False)):
                violations.append(f"{name}: neutral_grey_preserved=false")
            if channel_spread > 2:
                violations.append(f"{name}: channel_spread={channel_spread} > 2")
            if l_delta > 0.06:
                violations.append(f"{name}: |ΔL|={l_delta:.3f} > 0.06")
        elif name == "grey_blue_low_sat":
            if l_delta > 0.06:
                violations.append(f"{name}: |ΔL|={l_delta:.3f} > 0.06")
            if hue_delta > 5.0:
                violations.append(f"{name}: hue_shift={hue_delta:.1f}° > 5°")
        elif name in {"red", "green", "blue", "cyan", "magenta", "yellow"}:
            if chroma_ratio < 0.95 or chroma_ratio > 1.05:
                violations.append(f"{name}: chroma_ratio={chroma_ratio:.3f} outside 0.95-1.05")
            if hue_delta > 8.0:
                violations.append(f"{name}: hue_shift={hue_delta:.1f}° > 8°")
        elif name == "skin_orange":
            if hue_delta > 12.0:
                violations.append(f"{name}: hue_shift={hue_delta:.1f}° > 12°")
    return violations


@dataclass(frozen=True)
class ColorAccuracyDiagnosticResult:
    summary: str
    entries: list[dict[str, object]]


def run_color_accuracy_diagnostic(
    *, mapper, color_style: str = "reference"
) -> ColorAccuracyDiagnosticResult:
    samples = dict(GOLDEN_SWATCH_SAMPLES)
    entries: list[dict[str, object]] = []
    capped_count = 0
    for name, rgb in samples.items():
        mapped = mapper(rgb)
        if isinstance(mapped, tuple) and len(mapped) == 2:
            output_rgb, cap_applied = mapped
        else:
            output_rgb, cap_applied = mapped, False
        out = tuple(int(v) for v in np.asarray(output_rgb, dtype=np.uint8).tolist())
        metrics = color_pipeline_diagnostics(
            input_rgb=rgb,
            output_rgb=out,
            chroma_cap_applied=bool(cap_applied),
            color_style=color_style,
        )
        metrics["name"] = name
        metrics["output_rgb"] = out
        entries.append(metrics)
        capped_count += int(bool(metrics.get("chroma_cap_applied", False)))

    chroma_rows = [float(e["chroma_ratio"]) for e in entries if float(e["input_chroma"]) > 0.01]
    avg_ratio = float(np.mean(chroma_rows)) if chroma_rows else 1.0
    max_ratio = float(np.max(chroma_rows)) if chroma_rows else 1.0
    max_hue_delta = (
        float(np.max([abs(float(e["hue_difference_degrees"])) for e in entries]))
        if entries
        else 0.0
    )
    neutral_ok = all(bool(e["neutral_grey_preserved"]) for e in entries if "grey" in str(e["name"]))
    black_ok = all(
        str(e.get("black_cutoff_verdict")) == "pass"
        for e in entries
        if "grey_16" in str(e.get("name"))
    )
    neutral_floor_count = int(sum(1 for e in entries if bool(e.get("neutral_floor_applied"))))
    summary = (
        f"colour_accuracy avg_chroma_ratio={avg_ratio:.3f} max_chroma_ratio={max_ratio:.3f} "
        f"max_hue_delta={max_hue_delta:.2f} neutral_preserved={'yes' if neutral_ok else 'no'} "
        f"black_cutoff={'yes' if black_ok else 'no'} "
        f"neutral_floor_hits={neutral_floor_count} chroma_caps={capped_count}"
    )
    return ColorAccuracyDiagnosticResult(summary=summary, entries=entries)
