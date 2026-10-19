import asyncio
import subprocess
import sys
import threading
from importlib.metadata import PackageNotFoundError
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure import pandoc


class FakeInput:
    def __init__(self):
        self.data = b''

    def write(self, data):
        self.data += data

    def flush(self):
        pass

    def close(self):
        pass


class FakeStream:
    def __init__(self, data, ended):
        self.buffer = BytesIO(data)
        self.ended = ended
        self.exhausted = False

    def read(self, size):
        chunk = self.buffer.read(size)
        if not chunk:
            assert self.ended.wait(3)
            self.exhausted = True
        return chunk

    def at_eof(self):
        return self.exhausted

    def close(self):
        self.buffer.close()


class FakeProcess:
    def __init__(self, output=b'converted', stderr=b'', *, blocked=False, code=0):
        self.stdin = FakeInput()
        self.ended = threading.Event()
        self.stdout = FakeStream(output, self.ended)
        self.stderr = FakeStream(stderr, self.ended)
        self.returncode = None if blocked else code
        self.killed = False
        self.waited = False
        if not blocked:
            self.finish(code)

    def finish(self, code=-1):
        self.returncode = code
        self.ended.set()

    def kill(self):
        self.killed = True
        self.finish()

    def poll(self):
        return self.returncode

    def wait(self):
        assert self.ended.wait(3)
        self.waited = True
        return self.returncode


def ready_runner(monkeypatch, *, settings=None):
    runner = pandoc.PandocRunner(settings or Settings(_env_file=None))
    runner._binary = Path('bundled-pandoc.exe').resolve()
    return runner


def test_resolves_distribution_binary_without_system_search(monkeypatch, tmp_path):
    file = Path('pypandoc/files/pandoc.exe')
    binary = tmp_path / file
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'packaged')
    monkeypatch.setenv('PATH', 'different-pandoc')
    monkeypatch.setattr(pandoc, 'distribution', lambda _: SimpleNamespace(
        files=[file], locate_file=lambda path: tmp_path / path,
    ))
    assert pandoc.resolve_bundled_pandoc() == binary.resolve()


@pytest.mark.parametrize('missing_package', [True, False])
def test_missing_distribution_or_binary_returns_503(monkeypatch, missing_package):
    def find(_):
        if missing_package:
            raise PackageNotFoundError('pypandoc-binary')
        return SimpleNamespace(files=[], locate_file=lambda path: Path(path))
    monkeypatch.setattr(pandoc, 'distribution', find)
    with pytest.raises(AppError) as raised:
        pandoc.resolve_bundled_pandoc()
    assert (raised.value.code, raised.value.status_code) == ('DOCUMENT_EXPORT_UNAVAILABLE', 503)


def test_spawn_uses_fixed_arguments_and_binary_stdin(monkeypatch):
    async def scenario():
        process = FakeProcess()
        calls = []
        def spawn(args, **kwargs):
            calls.append((tuple(args), kwargs))
            return process
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        runner = ready_runner(monkeypatch)
        result = await runner.run(b'private data', source_format='json', target_format='docx',
                                  deadline=asyncio.get_running_loop().time() + 1)
        args, options = calls[0]
        assert '--sandbox' in args and '--fail-if-warnings' in args
        assert args[-2:] == ('-o', '-')
        assert 'private data' not in ' '.join(args)
        assert options.get('shell') is None
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            assert options['creationflags'] == subprocess.CREATE_NO_WINDOW
        assert process.stdin.data == b'private data' and result == b'converted'
        assert process.waited
    asyncio.run(scenario())


@pytest.mark.parametrize('failure,expected', [
    ('timeout', 'DOCUMENT_EXPORT_TIMEOUT'), ('overflow', 'EXPORT_OUTPUT_TOO_LARGE'),
    ('exit', 'DOCUMENT_EXPORT_FAILED'),
])
def test_process_failures_are_bounded_and_sanitized(monkeypatch, failure, expected):
    async def scenario():
        process = FakeProcess(b'x' * 20, b'private stderr' * 2000,
                              blocked=failure != 'exit', code=1)
        def spawn(*args, **kwargs):
            return process
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        settings = Settings(_env_file=None, document_export_max_output_bytes=10
                            if failure == 'overflow' else 100)
        runner = ready_runner(monkeypatch, settings=settings)
        with pytest.raises(AppError) as raised:
            await runner.run(b'private', source_format='gfm', target_format='json',
                             deadline=asyncio.get_running_loop().time() + .05)
        assert raised.value.code == expected
        assert 'private' not in str(raised.value)
        assert process.waited
        assert process.killed == (failure != 'exit')
    asyncio.run(scenario())


def test_large_stderr_is_drained_without_deadlock(monkeypatch):
    async def scenario():
        process = FakeProcess(stderr=b'x' * 100000)
        def spawn(*args, **kwargs):
            return process
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        result = await ready_runner(monkeypatch).run(
            b'body', source_format='gfm', target_format='json',
            deadline=asyncio.get_running_loop().time() + 1,
        )
        assert result == b'converted' and process.stderr.at_eof()
    asyncio.run(scenario())


def test_cancel_and_close_kill_and_reap_process(monkeypatch):
    async def scenario():
        process = FakeProcess(blocked=True)
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        def spawn(*args, **kwargs):
            loop.call_soon_threadsafe(started.set)
            return process
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        runner = ready_runner(monkeypatch)
        task = asyncio.create_task(runner.run(
            b'body', source_format='gfm', target_format='json',
            deadline=asyncio.get_running_loop().time() + 1,
        ))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await runner.aclose()
        await runner.aclose()
        assert process.killed and process.waited
        with pytest.raises(AppError) as raised:
            await runner.run(b'', source_format='gfm', target_format='json', deadline=0)
        assert raised.value.status_code == 503
    asyncio.run(scenario())


def test_cancel_during_spawn_still_reaps_created_process(monkeypatch):
    async def scenario():
        entered, release = threading.Event(), threading.Event()
        process = FakeProcess(blocked=True)
        def spawn(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return process
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        runner = ready_runner(monkeypatch)
        task = asyncio.create_task(runner.run(
            b'body', source_format='gfm', target_format='json',
            deadline=asyncio.get_running_loop().time() + 2,
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert process.killed and process.waited
    asyncio.run(scenario())


def test_close_reaps_active_process(monkeypatch):
    async def scenario():
        entered = asyncio.Event()
        process = FakeProcess(blocked=True)
        loop = asyncio.get_running_loop()
        def spawn(*args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            return process
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        runner = ready_runner(monkeypatch)
        task = asyncio.create_task(runner.run(
            b'body', source_format='gfm', target_format='json',
            deadline=asyncio.get_running_loop().time() + 2,
        ))
        await entered.wait()
        await asyncio.wait_for(runner.aclose(), 1)
        assert task.cancelled() and process.killed and process.waited
    asyncio.run(scenario())


def test_expired_deadline_does_not_spawn(monkeypatch):
    async def scenario():
        calls = []
        def spawn(*args, **kwargs):
            calls.append(args)
            return FakeProcess()
        monkeypatch.setattr(subprocess, 'Popen', spawn)
        with pytest.raises(AppError) as raised:
            await ready_runner(monkeypatch).run(
                b'body', source_format='gfm', target_format='json', deadline=0,
            )
        assert raised.value.code == 'DOCUMENT_EXPORT_TIMEOUT'
        assert not calls
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows uvicorn reload 使用 Selector loop')
def test_bundled_program_initializes_on_windows_selector_loop():
    loop = asyncio.SelectorEventLoop()
    runner = pandoc.PandocRunner(Settings(_env_file=None))
    try:
        loop.run_until_complete(runner.initialize())
        assert runner._binary is not None
    finally:
        loop.run_until_complete(runner.aclose())
        loop.close()


def test_real_output_overflow_does_not_hang_cleanup():
    script = '''
import asyncio, sys
from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.pandoc import PandocRunner
async def main():
    runner = PandocRunner(Settings(_env_file=None, document_export_max_output_bytes=100))
    try:
        await runner._execute(
            [sys.executable, '-c', 'import sys;sys.stdout.buffer.write(b"x"*2000000)'],
            b'', asyncio.get_running_loop().time()+1,
        )
    except AppError as exc:
        assert exc.code == 'EXPORT_OUTPUT_TOO_LARGE', exc.code
        print('overflow-reaped')
    else:
        raise AssertionError('Expected output limit error')
    await runner.aclose()
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                            timeout=4, check=True)
    assert b'overflow-reaped' in result.stdout
