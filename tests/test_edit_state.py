from core.edit_state import EditState
from core.lens_correction import LensSettings
from core.tone_pipeline import ToneSettings


def test_default_state_round_trips():
    state = EditState()
    assert EditState.from_json(state.to_json()) == state


def test_populated_state_round_trips():
    state = EditState(
        tone=ToneSettings(exposure=1.5, contrast=20.0, highlights=-30.0, shadows=40.0, whites=10.0, blacks=-5.0),
        lens=LensSettings(distortion=25.0, vignetting=-60.0, remove_chromatic_aberration=True),
        denoise_enabled=True,
    )
    assert EditState.from_json(state.to_json()) == state


def test_none_and_empty_json_yield_defaults():
    assert EditState.from_json(None) == EditState()
    assert EditState.from_json("") == EditState()


def test_corrupt_json_yields_defaults_instead_of_raising():
    assert EditState.from_json("{not valid json") == EditState()
    assert EditState.from_json("[1, 2, 3]") == EditState()


def test_missing_keys_fall_back_to_defaults():
    partial = '{"tone": {"exposure": 2.0}}'
    result = EditState.from_json(partial)

    assert result.tone.exposure == 2.0
    assert result.tone.contrast == 0.0  # missing -> default
    assert result.lens == LensSettings()  # whole section missing -> default
    assert result.denoise_enabled is False


def test_unknown_keys_are_ignored():
    forward_compatible = '{"tone": {"exposure": 1.0, "future_slider": 99.0}, "brand_new_section": {}}'
    result = EditState.from_json(forward_compatible)

    assert result.tone.exposure == 1.0
    assert not hasattr(result.tone, "future_slider")


def test_wrong_typed_values_fall_back_to_defaults():
    result = EditState.from_json('{"tone": {"exposure": "not a number"}}')
    assert result.tone.exposure == 0.0


def test_is_default_distinguishes_edited_from_untouched():
    assert EditState().is_default()
    assert not EditState(denoise_enabled=True).is_default()
    assert not EditState(tone=ToneSettings(exposure=0.5)).is_default()
