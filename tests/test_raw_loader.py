from pathlib import Path

import numpy as np
import pytest

from core.raw_loader import load_raw

SAMPLE_RAW = Path(__file__).parent.parent / "IMG_7346.CR3"


@pytest.mark.skipif(not SAMPLE_RAW.exists(), reason="sample CR3 not present")
def test_load_raw_decodes_sample_file():
    result = load_raw(SAMPLE_RAW)

    assert result.rgb.ndim == 3
    assert result.rgb.shape[2] == 3
    assert result.rgb.dtype == np.float32
    assert 0.0 <= result.rgb.min()
    assert result.rgb.max() <= 1.0

    assert result.lens_model == "RF100-400mm F5.6-8 IS USM"
    assert result.iso == 10000.0
    assert result.aperture == 8.0
    assert result.focal_length_mm == 400.0
