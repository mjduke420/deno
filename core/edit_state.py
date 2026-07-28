"""Per-photo edit settings, bundled for persistence in the catalog.

Edits are always read and written as a complete set, so they serialize to a single
JSON blob rather than being normalized into columns. Deserialization is deliberately
tolerant (missing/unknown keys, corrupt JSON) so a catalog written by an older or
newer build never hard-fails the library view.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace

from core.lens_correction import LensSettings
from core.tone_pipeline import ToneSettings

DEFAULT_DENOISE_AMOUNT = 0.75


@dataclass(frozen=True)
class EditState:
    tone: ToneSettings = field(default_factory=ToneSettings)
    lens: LensSettings = field(default_factory=LensSettings)
    denoise_enabled: bool = False
    # How much of the denoise result to blend in. Full strength scrubs fine detail
    # along with the noise, so the default holds back a little.
    denoise_amount: float = DEFAULT_DENOISE_AMOUNT  # 0.0 .. 1.0

    def to_json(self) -> str:
        return json.dumps(
            {
                "tone": asdict(self.tone),
                "lens": asdict(self.lens),
                "denoise_enabled": self.denoise_enabled,
                "denoise_amount": self.denoise_amount,
            }
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "EditState":
        """Rebuild an EditState, falling back to defaults for anything missing or unreadable."""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()

        amount = data.get("denoise_amount", DEFAULT_DENOISE_AMOUNT)
        return cls(
            tone=_build(ToneSettings, data.get("tone")),
            lens=_build(LensSettings, data.get("lens")),
            denoise_enabled=bool(data.get("denoise_enabled", False)),
            denoise_amount=_clamp_unit(amount),
        )

    def is_default(self) -> bool:
        """True when nothing has been adjusted — lets the UI show an 'edited' badge."""
        return self == EditState()


def _clamp_unit(value) -> float:
    """A stored amount outside 0..1 means a corrupt or hand-edited catalog."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return DEFAULT_DENOISE_AMOUNT


def _build(settings_cls, values):
    """Construct a settings dataclass from a dict, ignoring unknown keys and keeping
    defaults for any that are missing or of the wrong type."""
    settings = settings_cls()
    if not isinstance(values, dict):
        return settings

    known = {name: type(getattr(settings, name)) for name in settings.__dataclass_fields__}
    usable = {}
    for key, expected_type in known.items():
        if key not in values:
            continue
        value = values[key]
        if expected_type is bool:
            usable[key] = bool(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            usable[key] = float(value)
    return replace(settings, **usable)
