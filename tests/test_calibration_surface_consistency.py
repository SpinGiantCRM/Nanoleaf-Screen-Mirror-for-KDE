from pathlib import Path


def test_model_exposes_corner_anchor_fields() -> None:
    text = Path('src/nanoleaf_sync/config/model.py').read_text(encoding='utf-8')
    assert 'corner_anchor_top_left' in text
    assert 'corner_anchor_top_right' in text
