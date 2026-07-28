import pytest
from PIL import Image

from core.thumbnails import ThumbnailCache, cache_key


@pytest.fixture
def photo_file(tmp_path):
    """A stand-in 'RAW' file. Contents don't matter — the fake extractor ignores them."""
    path = tmp_path / "IMG_0001.CR3"
    path.write_bytes(b"pretend raw bytes")
    return path


class _FakeExtractor:
    """Yields a solid-colour image instead of touching LibRaw, so the cache logic
    can be tested without real RAW files."""

    def __init__(self, size=(2000, 1500), color=(255, 0, 0)):
        self.size = size
        self.color = color
        self.call_count = 0

    def __call__(self, path):
        self.call_count += 1
        return Image.new("RGB", self.size, self.color)


def test_generates_a_thumbnail_downscaled_to_the_requested_size(tmp_path, photo_file):
    cache = ThumbnailCache(tmp_path / "thumbs", size=256, extractor=_FakeExtractor())

    result = cache.get(photo_file)

    assert result is not None and result.exists()
    with Image.open(result) as img:
        assert max(img.size) == 256
        assert img.format == "JPEG"


def test_aspect_ratio_is_preserved(tmp_path, photo_file):
    cache = ThumbnailCache(tmp_path / "thumbs", size=256, extractor=_FakeExtractor(size=(2000, 1000)))

    with Image.open(cache.get(photo_file)) as img:
        assert img.size == (256, 128)


def test_second_call_is_served_from_cache_without_re_extracting(tmp_path, photo_file):
    extractor = _FakeExtractor()
    cache = ThumbnailCache(tmp_path / "thumbs", extractor=extractor)

    first = cache.get(photo_file)
    second = cache.get(photo_file)

    assert first == second
    assert extractor.call_count == 1


def test_modifying_the_source_file_invalidates_the_cached_thumbnail(tmp_path, photo_file):
    extractor = _FakeExtractor()
    cache = ThumbnailCache(tmp_path / "thumbs", extractor=extractor)
    before = cache.get(photo_file)

    photo_file.write_bytes(b"different raw bytes, different size")

    after = cache.get(photo_file)
    assert after != before  # different key -> different cache entry
    assert extractor.call_count == 2


def test_distinct_photos_get_distinct_cache_entries(tmp_path):
    first = tmp_path / "a.CR3"
    second = tmp_path / "b.CR3"
    first.write_bytes(b"aaa")
    second.write_bytes(b"bbb")
    cache = ThumbnailCache(tmp_path / "thumbs", extractor=_FakeExtractor())

    assert cache.get(first) != cache.get(second)


def test_unreadable_photo_returns_none_instead_of_raising(tmp_path):
    def exploding_extractor(path):
        raise OSError("corrupt file")

    cache = ThumbnailCache(tmp_path / "thumbs", extractor=exploding_extractor)
    photo = tmp_path / "broken.CR3"
    photo.write_bytes(b"garbage")

    assert cache.get(photo) is None


def test_missing_photo_returns_none_instead_of_raising(tmp_path):
    cache = ThumbnailCache(tmp_path / "thumbs", extractor=_FakeExtractor())
    assert cache.get(tmp_path / "does_not_exist.CR3") is None


def test_failed_extraction_leaves_no_partial_file_behind(tmp_path):
    def exploding_extractor(path):
        raise ValueError("decode blew up")

    thumbs = tmp_path / "thumbs"
    cache = ThumbnailCache(thumbs, extractor=exploding_extractor)
    photo = tmp_path / "broken.CR3"
    photo.write_bytes(b"garbage")

    cache.get(photo)

    assert list(thumbs.glob("*.jpg")) == []


def test_is_cached_reflects_generation_state(tmp_path, photo_file):
    cache = ThumbnailCache(tmp_path / "thumbs", extractor=_FakeExtractor())

    assert not cache.is_cached(photo_file)
    cache.get(photo_file)
    assert cache.is_cached(photo_file)


def test_clear_removes_cached_thumbnails(tmp_path, photo_file):
    cache = ThumbnailCache(tmp_path / "thumbs", extractor=_FakeExtractor())
    cache.get(photo_file)

    cache.clear()

    assert not cache.is_cached(photo_file)


def test_cache_key_changes_with_content_and_is_stable_otherwise(tmp_path):
    photo = tmp_path / "x.CR3"
    photo.write_bytes(b"one")
    original = cache_key(photo)

    assert cache_key(photo) == original  # stable across calls

    photo.write_bytes(b"a different length payload")
    assert cache_key(photo) != original
