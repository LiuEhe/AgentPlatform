import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.schemas.identity import AvatarChange
from app.services.user_service import UserService


@pytest.mark.parametrize("commit_started", [False, True])
def test_upload_preserves_files_when_commit_is_uncertain(commit_started):
    async def scenario():
        deleted = []

        async def replace(actor, path, *, state):
            state.commit_started = commit_started
            raise AppError("STORAGE_UNAVAILABLE", "failed", 503)

        store = SimpleNamespace(replace_avatar=replace)
        avatars = SimpleNamespace(publish=lambda *a: "new", discard=deleted.append)
        service = UserService(store, None, avatars)
        actor = SimpleNamespace(user=SimpleNamespace(user_id=uuid4()))
        with pytest.raises(AppError):
            await service.upload_avatar(actor, "a.png", b"data")
        assert deleted == ([] if commit_started else ["new"])
        await service.aclose()
    asyncio.run(scenario())


def test_upload_success_and_cleanup_failure_remain_successful():
    async def scenario():
        async def replace(actor, path, *, state):
            state.commit_started = True
            return AvatarChange("updated-profile", "old")

        def fail_cleanup(path):
            raise OSError("controlled")

        service = UserService(SimpleNamespace(replace_avatar=replace), None,
                              SimpleNamespace(publish=lambda *a: "new", discard=fail_cleanup))
        actor = SimpleNamespace(user=SimpleNamespace(user_id=uuid4()))
        assert await service.upload_avatar(actor, "a.png", b"data") == "updated-profile"
        await service.aclose()
    asyncio.run(scenario())


def test_cancelled_worker_keeps_slot_until_thread_exits():
    async def scenario():
        started = threading.Event()
        release = threading.Event()
        discarded = []

        def publish(*args):
            started.set()
            assert release.wait(5)
            return "new"

        avatars = SimpleNamespace(publish=publish, discard=discarded.append)
        service = UserService(None, None, avatars)
        actor = SimpleNamespace(user=SimpleNamespace(user_id=uuid4()))

        async def upload():
            async with service.avatar_upload_slot():
                await service.upload_avatar(actor, "a.png", b"data")

        try:
            async with service.avatar_upload_slot():
                task = asyncio.create_task(upload())
                while not started.is_set():
                    await asyncio.sleep(.001)
                task.cancel()
                await asyncio.sleep(.01)
                with pytest.raises(AppError) as busy:
                    async with service.avatar_upload_slot():
                        pass
                assert busy.value.code == "AVATAR_BUSY"
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert discarded == ["new"]
            async with service.avatar_upload_slot():
                pass
        finally:
            release.set()
            await service.aclose()
    asyncio.run(scenario())
