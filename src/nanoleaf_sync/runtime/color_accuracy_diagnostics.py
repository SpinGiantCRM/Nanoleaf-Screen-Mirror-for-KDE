from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.runtime.color_processing import color_pipeline_diagnostics


@dataclass(frozen=True)
class ColorAccuracyDiagnosticResult:
    summary: str
    entries: list[dict[str, object]]


def run_color_accuracy_diagnostic(*, mapper) -> ColorAccuracyDiagnosticResult:
    samples = {
        "neutral_grey": (128, 128, 128),
        "dark_grey": (52, 52, 52),
        "white": (255, 255, 255),
        "grey_blue": (92, 106, 116),
        "red": (220, 50, 45),
        "green": (40, 210, 90),
        "blue": (45, 95, 225),
    }
    entries: list[dict[str, object]] = []
    for name, rgb in samples.items():
        out = tuple(int(v) for v in np.asarray(mapper(rgb), dtype=np.uint8).tolist())
        metrics = color_pipeline_diagnostics(input_rgb=rgb, output_rgb=out)
        metrics["name"] = name
        entries.append(metrics)
    avg_ratio = float(np.mean([float(e["chroma_ratio"]) for e in entries if float(e["input_chroma"]) > 0.01]))
    neutral_ok = all(bool(e["neutral_grey_preserved"]) for e in entries if str(e["name"]).endswith("grey"))
    summary = f"colour_accuracy avg_chroma_ratio={avg_ratio:.3f} neutral_preserved={'yes' if neutral_ok else 'no'}"
    return ColorAccuracyDiagnosticResult(summary=summary, entries=entries)
