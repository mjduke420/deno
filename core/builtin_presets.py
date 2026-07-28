"""Presets shipped with the application.

Seeded once into a catalog. They are ordinary presets afterwards — editable and
deletable — so a preset you delete stays deleted rather than reappearing on the
next launch.
"""
from __future__ import annotations

from core.catalog import Catalog
from core.edit_state import EditState
from core.tone_pipeline import ToneSettings

SEEDED_MARKER = "builtin_presets_seeded"

BUILTIN_PRESETS: dict[str, EditState] = {
    # Transcribed from Lightroom's Basic panel.
    "Skittles": EditState(
        tone=ToneSettings(
            temperature=5850.0,
            tint=-8.0,
            exposure=0.0,
            contrast=30.0,
            highlights=-100.0,
            shadows=74.0,
            whites=38.0,
            blacks=-20.0,
            clarity=15.0,
            dehaze=30.0,
            vibrance=40.0,
            saturation=-5.0,
        )
    ),
}


def seed_builtin_presets(catalog: Catalog) -> list[str]:
    """Add the built-in presets to a catalog that has not had them. Returns the
    names actually added."""
    if catalog.get_setting(SEEDED_MARKER):
        return []

    added = []
    for name, edits in BUILTIN_PRESETS.items():
        if catalog.get_preset_by_name(name) is None:
            catalog.save_preset(name, edits.without_denoise())
            added.append(name)

    catalog.set_setting(SEEDED_MARKER, "1")
    return added
