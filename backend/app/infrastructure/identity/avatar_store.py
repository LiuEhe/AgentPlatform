"""头像图片归一化与受限本地文件操作，不解释账号权限或 HTTP。"""

import stat
import warnings
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

MAX_AVATAR_BYTES = 2_097_152


class AvatarStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _safe(self, relative_path):
        try:
            owner, filename = relative_path.split("/")
            if str(UUID(owner)) != owner or not filename.endswith(".png"):
                raise ValueError
            if str(UUID(filename[:-4])) + ".png" != filename:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise AppError("AVATAR_UNAVAILABLE", "头像文件不可用", 503) from None
        target = self.root / owner / filename
        for current in (self.root, self.root / owner, target):
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise AppError("AVATAR_UNAVAILABLE", "头像文件不可用", 503)
        if not target.resolve().is_relative_to(self.root):
            raise AppError("AVATAR_UNAVAILABLE", "头像文件不可用", 503)
        return target

    def publish(self, user_id, filename, content):
        if len(content) > MAX_AVATAR_BYTES:
            raise AppError("AVATAR_TOO_LARGE", "头像不能超过2 MB", 413)
        if Path(filename).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise AppError("AVATAR_TYPE_UNSUPPORTED", "请选择JPG、PNG或WebP图片", 415)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content), formats=["JPEG", "PNG", "WEBP"]) as source:
                    if (max(source.size) > 8192 or source.width * source.height > 16_000_000
                            or getattr(source, "n_frames", 1) != 1):
                        raise ValueError("image limits")
                    source.verify()
                with Image.open(BytesIO(content), formats=["JPEG", "PNG", "WEBP"]) as source:
                    source.load()
                    oriented = ImageOps.exif_transpose(source)
                    oriented.thumbnail((512, 512))
                    mode = "RGBA" if "A" in oriented.getbands() or "transparency" in source.info \
                        else "RGB"
                    clean = Image.new(mode, oriented.size)
                    clean.paste(oriented.convert(mode))
                    output = BytesIO()
                    clean.save(output, format="PNG")
                    encoded = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
                Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise AppError("AVATAR_INVALID", "图片无效、尺寸超限或不是静态图片", 422) from None
        if len(encoded) > MAX_AVATAR_BYTES:
            raise AppError("AVATAR_TOO_LARGE", "处理后的头像超过大小限制", 413)
        relative = f"{UUID(str(user_id))}/{uuid4()}.png"
        created = False
        try:
            path = self._safe(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path = self._safe(relative)
            with path.open("xb") as target:
                created = True
                target.write(encoded)
        except OSError:
            if created:
                self.discard(relative)
            raise AppError("AVATAR_UNAVAILABLE", "头像保存失败，请重试", 503) from None
        return relative

    def read(self, relative_path):
        try:
            return self._safe(relative_path).read_bytes()
        except FileNotFoundError:
            raise AppError("AVATAR_NOT_FOUND", "尚未设置头像或头像文件缺失", 404) from None
        except OSError:
            raise AppError("AVATAR_UNAVAILABLE", "头像读取失败，请重试", 503) from None

    def discard(self, relative_path):
        try:
            self._safe(relative_path).unlink(missing_ok=True)
        except OSError:
            raise AppError("AVATAR_UNAVAILABLE", "头像清理失败", 503) from None
