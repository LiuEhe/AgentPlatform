import asyncio

import pytest

from app.core.errors import AppError


def test_passwords_hash_without_trimming_and_reject_invalid():
    from app.infrastructure.identity.passwords import PasswordHasher

    async def scenario():
        hasher = PasswordHasher()
        password = " long password "
        encoded = await hasher.hash(password)
        assert encoded.startswith("$argon2id$")
        assert (await hasher.verify(password, encoded)).valid
        assert not (await hasher.verify(password.strip(), encoded)).valid
        for invalid in ("short", "x" * 21):
            with pytest.raises(AppError):
                await hasher.hash(invalid)
        await hasher.aclose()

    asyncio.run(scenario())


def test_registration_and_login_limits_have_independent_atomic_windows():
    from app.infrastructure.identity.auth_limits import AuthAttemptLimiter

    now = [0.0]
    limiter = AuthAttemptLimiter(clock=lambda: now[0])
    assert [limiter.reserve_registration("ip") for _ in range(10)] == [None] * 10
    assert limiter.reserve_registration("ip") == 600
    for _ in range(5):
        limiter.failed_login("ip", "alice")
    assert limiter.check_login("ip", "alice") == 600
    assert limiter.check_login("ip", "bob") is None
    limiter.succeeded_login("ip", "alice")
    assert limiter.check_login("ip", "alice") is None
    assert limiter.reserve_registration("ip") == 600
    now[0] = 600
    assert limiter.reserve_registration("ip") is None


def test_cancelled_hash_holds_its_slot_until_the_worker_finishes():
    import threading
    from types import SimpleNamespace

    from app.infrastructure.identity.passwords import PasswordHasher

    async def scenario():
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        def blocked(password):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            return 'encoded'
        hasher = PasswordHasher(concurrency=1, queue_size=0)
        hasher._hash = SimpleNamespace(hash=blocked)
        running = asyncio.create_task(hasher.hash('long-enough-password'))
        await entered.wait()
        running.cancel()
        await asyncio.sleep(0)
        try:
            assert not running.done()
            with pytest.raises(AppError) as error:
                await hasher.hash('other-long-password')
            assert error.value.code == 'AUTH_BUSY'
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert await hasher.hash('other-long-password') == 'encoded'
        await hasher.aclose()

    asyncio.run(scenario())
