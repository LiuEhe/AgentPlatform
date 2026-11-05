from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.core.errors import AppError


def image_bytes(fmt="PNG", size=(32, 32), **kwargs):
    buffer = BytesIO()
    Image.new("RGBA" if fmt != "JPEG" else "RGB", size, "red").save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def test_avatar_formats_normalize_to_png(tmp_path):
    from app.infrastructure.identity.avatar_store import AvatarStore
    store = AvatarStore(tmp_path)
    for fmt, extension in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")):
        path = store.publish(uuid4(), "avatar." + extension, image_bytes(fmt, (900, 600)))
        with Image.open(BytesIO(store.read(path))) as result:
            assert result.format == "PNG" and result.size == (512, 341)
            assert "exif" not in result.info
        store.discard(path)
        store.discard(path)
        with pytest.raises(AppError) as missing:
            store.read(path)
        assert missing.value.code == "AVATAR_NOT_FOUND"


@pytest.mark.parametrize("filename,data,code", [
    ("a.png", b"", "AVATAR_INVALID"), ("a.png", b"x" * 2097153, "AVATAR_TOO_LARGE"),
    ("a.svg", b"<svg/>", "AVATAR_TYPE_UNSUPPORTED"),
    ("a.png", b"not an image", "AVATAR_INVALID"),
], ids=["empty", "too-large", "svg", "garbage"])
def test_avatar_rejects_unsupported_or_invalid_data(tmp_path, filename, data, code):
    from app.infrastructure.identity.avatar_store import AvatarStore
    with pytest.raises(AppError) as error:
        AvatarStore(tmp_path).publish(uuid4(), filename, data)
    assert error.value.code == code
    assert not list(tmp_path.rglob("*.png"))


def test_avatar_paths_stay_inside_root(tmp_path):
    from app.infrastructure.identity.avatar_store import AvatarStore
    store = AvatarStore(tmp_path)
    for path in ("../outside.png", "/tmp/a.png", "a/b.png", "a\\b.png", "C:/a.png"):
        with pytest.raises(AppError):
            store.read(path)


def test_avatar_rejects_animation_and_oversize_dimensions(tmp_path):
    from app.infrastructure.identity.avatar_store import AvatarStore
    store = AvatarStore(tmp_path)
    first = Image.new("RGB", (2, 2), "red")
    buffer = BytesIO()
    first.save(buffer, "PNG", save_all=True, append_images=[Image.new("RGB", (2, 2), "blue")])
    for data in (buffer.getvalue(), image_bytes(size=(8193, 1)), image_bytes(size=(4001, 4000))):
        with pytest.raises(AppError) as error:
            store.publish(uuid4(), "a.png", data)
        assert error.value.code == "AVATAR_INVALID"


def test_avatar_keeps_transparency_and_exif_orientation(tmp_path):
    from app.infrastructure.identity.avatar_store import AvatarStore
    store = AvatarStore(tmp_path)
    uid = uuid4()
    image = Image.new("RGBA", (10, 20), (1, 2, 3, 40))
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private metadata"
    buffer = BytesIO()
    image.save(buffer, "PNG", exif=exif)
    path = store.publish(uid, "a.png", buffer.getvalue())
    with Image.open(BytesIO(store.read(path))) as result:
        assert result.size == (20, 10) and result.getpixel((0, 0))[3] == 40
        assert not result.getexif()
