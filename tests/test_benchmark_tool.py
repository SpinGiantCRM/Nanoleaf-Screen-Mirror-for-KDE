from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanoleaf_sync.tools import benchmark as benchmark_module


def test_run_benchmark_production_preset_has_expected_metrics() -> None:
    result = benchmark_module.run_benchmark(preset_name="production")
    assert result["preset"] == "production"
    metrics = result["metrics"]
    for name in ("zone_sampling", "colour_pipeline", "hid_frame_build"):
        block = metrics[name]
        assert block["samples"] > 0
        assert block["p95_ms"] >= 0.0


def test_compare_against_baseline_passes_for_generous_budgets() -> None:
    result = benchmark_module.run_benchmark(preset_name="production")
    baseline = {
        "metrics": {
            "zone_sampling": {"p95_ms_max": 10_000.0},
            "colour_pipeline": {"p95_ms_max": 10_000.0},
            "hid_frame_build": {"p95_ms_max": 10_000.0},
        }
    }
    assert benchmark_module.compare_against_baseline(result, baseline) == []


def test_compare_against_baseline_reports_regression() -> None:
    result = {
        "metrics": {
            "zone_sampling": {"p95_ms": 50.0},
        }
    }
    baseline = {
        "metrics": {
            "zone_sampling": {"p95_ms_max": 10.0},
        }
    }
    failures = benchmark_module.compare_against_baseline(result, baseline)
    assert failures
    assert "zone_sampling" in failures[0]


def test_main_writes_json_and_compares(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "zone_sampling": {"p95_ms_max": 10_000.0},
                    "colour_pipeline": {"p95_ms_max": 10_000.0},
                    "hid_frame_build": {"p95_ms_max": 10_000.0},
                }
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "result.json"
    code = benchmark_module.main(
        [
            "--preset",
            "production",
            "--json",
            str(out_path),
            "--compare",
            str(baseline_path),
        ]
    )
    assert code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["preset"] == "production"


def test_main_unknown_preset_returns_error() -> None:
    with pytest.raises(SystemExit) as exc:
        benchmark_module.main(["--preset", "missing"])
    assert int(exc.value.code) == 2
