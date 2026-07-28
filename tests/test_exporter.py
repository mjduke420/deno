import numpy as np
from PIL import Image

from core.catalog import Photo
from core.edit_state import EditState
from core.exporter import export_jpeg, export_photos, render_with_edits
from core.tone_pipeline import ToneSettings


def _gradient_rgb(size: int = 128) -> np.ndarray:
    x = np.linspace(0, 1, size, dtype=np.float32)
    y = np.linspace(0, 1, size, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    return np.stack([xx, yy, (xx + yy) / 2], axis=-1).astype(np.float32)


def _make_photo(tmp_path, name="IMG_0001.jpg", edits=None, color=(120, 120, 120)) -> Photo:
    """A catalog record backed by a real (small, synthetic) image file."""
    path = tmp_path / name
    Image.new("RGB", (32, 24), color).save(path, format="JPEG")
    return Photo(
        id=abs(hash(name)) % 10_000,
        folder_id=1,
        path=str(path),
        filename=name,
        rating=5,
        flag="pick",
        color_label=None,
        is_missing=False,
        edits_json=(edits or EditState()).to_json(),
    )


def test_export_writes_a_valid_jpeg_with_correct_dimensions(tmp_path):
    rgb = _gradient_rgb()
    out_path = tmp_path / "out.jpg"

    export_jpeg(rgb, str(out_path), quality=90)

    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.format == "JPEG"
        assert img.size == (128, 128)


def test_higher_quality_produces_a_larger_file(tmp_path):
    rgb = _gradient_rgb()
    low_path = tmp_path / "low.jpg"
    high_path = tmp_path / "high.jpg"

    export_jpeg(rgb, str(low_path), quality=10)
    export_jpeg(rgb, str(high_path), quality=95)

    assert high_path.stat().st_size > low_path.stat().st_size


def test_export_accepts_already_uint8_srgb_input(tmp_path):
    srgb8 = np.full((32, 32, 3), 128, dtype=np.uint8)
    out_path = tmp_path / "out.jpg"

    export_jpeg(srgb8, str(out_path), quality=90)

    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (32, 32)


# ---------- batch export ----------


def test_render_with_edits_applies_the_photos_own_adjustments(tmp_path):
    photo = _make_photo(tmp_path, color=(80, 80, 80))

    neutral = render_with_edits(photo.path, EditState())
    brightened = render_with_edits(photo.path, EditState(tone=ToneSettings(exposure=2.0)))

    assert brightened.mean() > neutral.mean()


def test_batch_export_writes_one_jpeg_per_photo(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    photos = [_make_photo(source, f"IMG_{i}.jpg") for i in range(3)]
    output = tmp_path / "out"

    result = export_photos(photos, output, quality=90)

    assert result.exported == 3
    assert result.failed == 0
    assert sorted(p.name for p in output.glob("*.jpg")) == ["IMG_0.jpg", "IMG_1.jpg", "IMG_2.jpg"]


def test_batch_export_applies_each_photos_edits_independently(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dark = _make_photo(source, "dark.jpg", color=(80, 80, 80))
    bright = _make_photo(source, "bright.jpg", edits=EditState(tone=ToneSettings(exposure=2.0)), color=(80, 80, 80))
    output = tmp_path / "out"

    export_photos([dark, bright], output, quality=95)

    with Image.open(output / "dark.jpg") as img:
        dark_mean = np.asarray(img).mean()
    with Image.open(output / "bright.jpg") as img:
        bright_mean = np.asarray(img).mean()
    assert bright_mean > dark_mean


def test_batch_export_creates_the_output_directory(tmp_path):
    photo = _make_photo(tmp_path)
    output = tmp_path / "does" / "not" / "exist"

    export_photos([photo], output, quality=90)

    assert (output / "IMG_0001.jpg").exists()


def test_batch_export_does_not_overwrite_same_named_photos(tmp_path):
    first_shoot = tmp_path / "a"
    second_shoot = tmp_path / "b"
    first_shoot.mkdir()
    second_shoot.mkdir()
    photos = [_make_photo(first_shoot, "IMG_1234.jpg"), _make_photo(second_shoot, "IMG_1234.jpg")]
    output = tmp_path / "out"

    result = export_photos(photos, output, quality=90)

    assert result.exported == 2
    assert sorted(p.name for p in output.glob("*.jpg")) == ["IMG_1234.jpg", "IMG_1234_2.jpg"]


def test_batch_export_reports_progress(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    photos = [_make_photo(source, f"IMG_{i}.jpg") for i in range(3)]
    seen = []

    export_photos(photos, tmp_path / "out", quality=90, progress_cb=lambda d, t: seen.append((d, t)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_batch_export_can_be_cancelled(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    photos = [_make_photo(source, f"IMG_{i}.jpg") for i in range(5)]
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2

    result = export_photos(photos, tmp_path / "out", quality=90, should_cancel=should_cancel)

    assert result.cancelled is True
    assert result.exported < 5


def test_unreadable_photo_is_counted_but_does_not_abort_the_batch(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    good = _make_photo(source, "good.jpg")
    broken_path = source / "broken.jpg"
    broken_path.write_bytes(b"not a real jpeg")
    broken = Photo(
        id=999,
        folder_id=1,
        path=str(broken_path),
        filename="broken.jpg",
        rating=0,
        flag="none",
        color_label=None,
        is_missing=False,
    )

    result = export_photos([good, broken], tmp_path / "out", quality=90)

    assert result.exported == 1
    assert result.failed == 1
