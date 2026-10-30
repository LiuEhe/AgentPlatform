"""本地附件存储；仅接受服务生成的标识，不解释 HTTP 或 Agent 材料。"""

import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from app.core.errors import AppError

BACKEND_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class StagedFile:
    staging_path: str
    relative_dir: str


@dataclass(frozen=True)
class StoredPaths:
    source_path: str
    content_path: str


class LocalFileStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or BACKEND_ROOT / "documents").resolve()

    @staticmethod
    def _error():
        return AppError("FILE_UNAVAILABLE", "材料文件不可用，请重新上传", 503)

    def _safe(self, relative: str) -> Path:
        parts = relative.split("/")
        if (
            not relative or "\\" in relative or ":" in relative
            or PurePosixPath(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise self._error()
        target = self.root.joinpath(*parts)
        current = self.root
        for part in parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise self._error()
        if not target.resolve().is_relative_to(self.root):
            raise self._error()
        return target

    def _published_dir(self, relative: str) -> Path:
        try:
            agent_id, session_id, file_id = relative.split("/")
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", agent_id):
                raise ValueError
            if str(UUID(session_id)) != session_id or str(UUID(file_id)) != file_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise self._error() from None
        return self._safe(relative)

    def _staging_dir(self, staged: StagedFile) -> Path:
        try:
            prefix, upload_id = staged.staging_path.split("/")
            if prefix != ".staging" or str(UUID(upload_id)) != upload_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise self._error() from None
        return self._safe(staged.staging_path)

    def stage(self, agent_id, session_id, file_id, original_bytes, markdown) -> StagedFile:
        relative = f"{agent_id}/{session_id}/{file_id}"
        self._published_dir(relative)
        staged = StagedFile(f".staging/{uuid4()}", relative)
        directory = self._staging_dir(staged)
        try:
            directory.mkdir(parents=True)
            (directory / "source.docx").write_bytes(original_bytes)
            (directory / "content.md").write_bytes(markdown.encode("utf-8"))
        except OSError:
            self.discard_staged(staged)
            raise self._error() from None
        return staged

    def publish(self, staged: StagedFile) -> StoredPaths:
        source = self._staging_dir(staged)
        target = self._published_dir(staged.relative_dir)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise self._error()
            os.rename(source, target)
        except OSError:
            raise self._error() from None
        return StoredPaths(
            f"{staged.relative_dir}/source.docx", f"{staged.relative_dir}/content.md"
        )

    def read_markdown(self, relative_path: str) -> str:
        try:
            directory, filename = relative_path.rsplit("/", 1)
            if filename != "content.md":
                raise self._error()
            self._published_dir(directory)
            return self._safe(relative_path).read_bytes().decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            raise self._error() from None

    def _discard(self, directory: Path):
        # 只删除本次生成目录；先校验其全部内容，拒绝 reparse point/junction。
        if directory.exists():
            for child in directory.rglob("*"):
                self._safe(child.relative_to(self.root).as_posix())
            shutil.rmtree(directory)

    def discard_staged(self, staged: StagedFile):
        self._discard(self._staging_dir(staged))

    def discard_published(self, paths: StoredPaths):
        directory, filename = paths.source_path.rsplit("/", 1)
        if filename != "source.docx" or paths.content_path != f"{directory}/content.md":
            raise self._error()
        self._discard(self._published_dir(directory))
