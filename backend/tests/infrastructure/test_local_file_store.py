"""附件原件和正文落盘，拒绝路径逃逸及覆盖。"""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.errors import AppError


def test_file_roundtrip_and_no_overwrite(tmp_path):
    from app.infrastructure.documents.local_file_store import LocalFileStore

    store = LocalFileStore(tmp_path / "documents")
    session_id, file_id = str(uuid4()), str(uuid4())
    staged = store.stage(
        "conversation_assistant", session_id, file_id, b"docx\x00bytes", "正文\r\n# x"
    )
    paths = store.publish(staged)
    assert paths.source_path == f"conversation_assistant/{session_id}/{file_id}/source.docx"
    assert (store.root / paths.source_path).read_bytes() == b"docx\x00bytes"
    assert store.read_markdown(paths.content_path) == "正文\r\n# x"
    duplicate = store.stage(
        "conversation_assistant", session_id, file_id, b"replacement", "changed"
    )
    with pytest.raises(AppError):
        store.publish(duplicate)
    store.discard_staged(duplicate)
    assert (store.root / paths.source_path).read_bytes() == b"docx\x00bytes"
    store.discard_published(paths)
    assert not (store.root / paths.content_path).exists()


@pytest.mark.parametrize(
    "path", ["../outside", "/outside", "C:/outside", "C:outside", "//host/share", "a\\b", "a/../b"]
)
def test_read_rejects_untrusted_path(tmp_path, path):
    from app.infrastructure.documents.local_file_store import LocalFileStore

    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    store = LocalFileStore(tmp_path / "documents")
    with pytest.raises(AppError) as error:
        store.read_markdown(path)
    assert error.value.code == "FILE_UNAVAILABLE"
    assert outside.read_bytes() == b"keep"


def test_missing_invalid_utf8_and_linked_content_fail(tmp_path):
    from app.infrastructure.documents.local_file_store import LocalFileStore

    store = LocalFileStore(tmp_path / "documents")
    staged = store.stage("conversation_assistant", str(uuid4()), str(uuid4()), b"bytes", "正文")
    paths = store.publish(staged)
    content = store.root / paths.content_path
    content.write_bytes(b"\xff")
    with pytest.raises(AppError, match="材料文件不可用"):
        store.read_markdown(paths.content_path)
    content.unlink()
    with pytest.raises(AppError):
        store.read_markdown(paths.content_path)
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    # Windows 创建普通 symlink 需要开发者模式/额外权限；junction 用单独测试覆盖。
    if os.name != "nt":
        content.symlink_to(outside)
        with pytest.raises(AppError):
            store.read_markdown(paths.content_path)
        with pytest.raises(AppError):
            store.discard_published(paths)
        assert outside.read_text(encoding="utf-8") == "secret"


def test_configured_relative_root_is_independent_of_cwd(tmp_path, monkeypatch):
    from app.core.config import Settings
    from app.infrastructure.documents.local_file_store import LocalFileStore

    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[2]
    assert LocalFileStore().root == root / "documents"
    assert Settings(_env_file=None, documents_dir="other").documents_root == root / "other"


def test_directory_link_cannot_escape_or_be_cleaned(tmp_path):
    from app.infrastructure.documents.local_file_store import LocalFileStore, StoredPaths

    store = LocalFileStore(tmp_path / "documents")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "content.md"
    secret.write_bytes(b"keep")
    session_id, file_id = str(uuid4()), str(uuid4())
    relative = f"conversation_assistant/{session_id}/{file_id}"
    linked = store.root / relative
    linked.parent.mkdir(parents=True)
    if os.name == "nt":
        import subprocess

        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
            check=True, capture_output=True,
        )
    else:
        linked.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(AppError):
            store.read_markdown(f"{relative}/content.md")
        with pytest.raises(AppError):
            store.discard_published(
                StoredPaths(f"{relative}/source.docx", f"{relative}/content.md")
            )
        assert secret.read_bytes() == b"keep"
    finally:
        if os.name == "nt":
            os.rmdir(linked)  # 只移除本次测试 junction，不递归进入目标。
        else:
            linked.unlink()
