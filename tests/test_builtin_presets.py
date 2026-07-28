"""The shipped presets, and the rule that presets carry a look but not denoise."""
import pytest

from core.builtin_presets import BUILTIN_PRESETS, SEEDED_MARKER, seed_builtin_presets
from core.catalog import Catalog
from core.edit_state import DEFAULT_DENOISE_AMOUNT, EditState
from core.tone_pipeline import ToneSettings


@pytest.fixture
def catalog():
    with Catalog(":memory:") as cat:
        yield cat


def test_skittles_matches_the_lightroom_settings_it_came_from():
    tone = BUILTIN_PRESETS["Skittles"].tone

    assert tone.temperature == 5850.0
    assert tone.tint == -8.0
    assert tone.exposure == 0.0
    assert tone.contrast == 30.0
    assert tone.highlights == -100.0
    assert tone.shadows == 74.0
    assert tone.whites == 38.0
    assert tone.blacks == -20.0
    assert tone.clarity == 15.0
    assert tone.dehaze == 30.0
    assert tone.vibrance == 40.0
    assert tone.saturation == -5.0


def test_seeding_adds_the_builtin_presets(catalog):
    added = seed_builtin_presets(catalog)

    assert "Skittles" in added
    stored = catalog.get_preset_by_name("Skittles")
    assert stored is not None
    assert stored.edits.tone.contrast == 30.0


def test_seeding_twice_does_not_duplicate(catalog):
    seed_builtin_presets(catalog)
    added_again = seed_builtin_presets(catalog)

    assert added_again == []
    assert len(catalog.list_presets()) == len(BUILTIN_PRESETS)


def test_a_deleted_builtin_preset_stays_deleted(catalog):
    """Re-seeding on every launch would resurrect presets the user threw away."""
    seed_builtin_presets(catalog)
    preset = catalog.get_preset_by_name("Skittles")
    catalog.delete_preset(preset.id)

    seed_builtin_presets(catalog)

    assert catalog.get_preset_by_name("Skittles") is None


def test_seeding_marks_the_catalog(catalog):
    assert catalog.get_setting(SEEDED_MARKER) is None
    seed_builtin_presets(catalog)
    assert catalog.get_setting(SEEDED_MARKER) == "1"


def test_builtin_presets_carry_no_denoise():
    for name, state in BUILTIN_PRESETS.items():
        assert state.denoise_enabled is False, name


# ---------- presets exclude denoise ----------


def test_without_denoise_keeps_the_look_and_drops_the_denoise():
    state = EditState(
        tone=ToneSettings(contrast=40.0, temperature=6500.0),
        denoise_enabled=True,
        denoise_amount=0.25,
    )

    stripped = state.without_denoise()

    assert stripped.tone == state.tone  # look preserved
    assert stripped.lens == state.lens
    assert stripped.denoise_enabled is False
    assert stripped.denoise_amount == DEFAULT_DENOISE_AMOUNT


def test_merged_with_takes_the_other_photos_denoise():
    preset = EditState(tone=ToneSettings(contrast=40.0))
    photo = EditState(tone=ToneSettings(contrast=5.0), denoise_enabled=True, denoise_amount=0.5)

    result = preset.merged_with(photo)

    assert result.tone.contrast == 40.0  # the preset's look
    assert result.denoise_enabled is True  # the photo's own denoise
    assert result.denoise_amount == 0.5


def test_saved_preset_round_trips_without_denoise(catalog):
    state = EditState(tone=ToneSettings(vibrance=30.0), denoise_enabled=True, denoise_amount=0.25)

    catalog.save_preset("Look", state.without_denoise())

    stored = catalog.get_preset_by_name("Look").edits
    assert stored.tone.vibrance == 30.0
    assert stored.denoise_enabled is False
