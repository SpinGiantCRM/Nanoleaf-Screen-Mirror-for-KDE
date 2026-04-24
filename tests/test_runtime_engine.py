from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import _mapping_signature


def test_mapping_signature_tracks_reverse_and_model() -> None:
    cfg = AppConfig(
        device_zone_count=10,
        calibration_model='corner_anchored',
        calibration=CalibrationConfig(reverse_zones=True),
    )
    sig = _mapping_signature(source_zone_count=10, config=cfg, detected_device_zone_count=10)
    assert sig[0] == 10
    assert isinstance(sig[4], bool)
