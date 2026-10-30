"""本地附件存储；仅接受服务生成的标识，不解释 HTTP 或 Agent 材料。"""

import json
import logging
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from app.core.errors import AppError

BACKEND_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionDeletionIntent:
    version: int
    agent_id: str
    session_id: str


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

    def _session_dir(self, agent_id: str, session_id: str) -> Path:
        try:
            if agent_id != "conversation_assistant" or str(UUID(session_id)) != session_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise self._error() from None
        return self._safe(f"{agent_id}/{session_id}")

    def _intent_path(self, session_id: str) -> Path:
        self._session_dir("conversation_assistant", session_id)
        return self._safe(f".deletions/{session_id}.json")

    def validate_session_deletion(self, agent_id: str, session_id: str) -> None:
        directory = self._session_dir(agent_id, session_id)
        self._intent_path(session_id)
        if directory.exists():
            for child in directory.rglob("*"):
                self._safe(child.relative_to(self.root).as_posix())

    def write_deletion_intent(self, agent_id: str, session_id: str) -> SessionDeletionIntent:
        self.validate_session_deletion(agent_id, session_id)
        target = self._intent_path(session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._safe(f".deletions/{uuid4()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump({"version": 1, "agent_id": agent_id, "session_id": session_id}, stream)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return SessionDeletionIntent(1, agent_id, session_id)

    def read_deletion_intent(self, session_id: str) -> SessionDeletionIntent | None:
        path = self._intent_path(session_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError):
            raise self._error() from None
        if (not isinstance(payload, dict)
                or set(payload) != {"version", "agent_id", "session_id"}
                or type(payload["version"]) is not int or payload["version"] != 1
                or payload["session_id"] != session_id):
            raise self._error()
        self._session_dir(payload["agent_id"], payload["session_id"])
        return SessionDeletionIntent(**payload)

    def list_deletion_intents(self) -> list[SessionDeletionIntent]:
        directory = self._safe(".deletions")
        intents = []
        for path in directory.glob("*.json"):
            try:
                intent = self.read_deletion_intent(path.stem)
                if intent:
                    intents.append(intent)
            except (AppError, OSError) as exc:
                logger.warning("deletion_intent_invalid error_type=%s", type(exc).__name__)
        return intents

    def discard_session(self, agent_id: str, session_id: str) -> None:
        self._discard(self._session_dir(agent_id, session_id))

    def discard_deletion_intent(self, session_id: str) -> None:
        self._intent_path(session_id).unlink(missing_ok=True)
