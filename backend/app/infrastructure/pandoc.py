"""执行 Python 依赖自带的 Pandoc，限制进程时间和管道输出。"""

import asyncio
import os
import subprocess
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Literal

from app.core.config import Settings
from app.core.errors import AppError


def resolve_bundled_pandoc() -> Path:
    """只接受 pypandoc-binary 安装清单中的程序，不搜索系统 PATH。"""
    try:
        package = distribution("pypandoc-binary")
        root = Path(package.locate_file("pypandoc")).resolve()
        for entry in package.files or ():
            if entry.as_posix() not in {
                "pypandoc/files/pandoc", "pypandoc/files/pandoc.exe",
            }:
                continue
            binary = Path(package.locate_file(entry)).resolve()
            if binary.is_relative_to(root) and binary.is_file():
                return binary
    except (PackageNotFoundError, OSError):
        pass
    raise AppError("DOCUMENT_EXPORT_UNAVAILABLE", "文档转换程序不可用", 503)


async def _settle(task: asyncio.Task):
    """等待清理真正结束；重复取消不能留下进程或管道任务。"""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class PandocRunner:
    """持有包内程序路径，并跟踪此实例的活动执行。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._binary: Path | None = None
        self._closed = False
        self._operations: set[asyncio.Task] = set()

    async def initialize(self) -> None:
        self._binary = resolve_bundled_pandoc()
        try:
            version = await self._execute(
                [str(self._binary), "--version"], b"",
                asyncio.get_running_loop().time()
                + min(5, self._settings.document_export_timeout_seconds),
            )
            if not version.startswith(b"pandoc "):
                raise ValueError("Invalid version response")
        except (AppError, ValueError) as exc:
            self._binary = None
            raise AppError("DOCUMENT_EXPORT_UNAVAILABLE", "文档转换程序不可用", 503) from exc

    async def run(
        self, data: bytes, *, source_format: Literal["gfm", "json"],
        target_format: Literal["json", "docx"], deadline: float,
    ) -> bytes:
        if self._closed or self._binary is None:
            raise AppError("DOCUMENT_EXPORT_UNAVAILABLE", "文档转换服务不可用", 503)
        if (source_format, target_format) not in {("gfm", "json"), ("json", "docx")}:
            raise AppError("DOCUMENT_EXPORT_FAILED", "文档转换格式无效", 500)
        args = [str(self._binary), f"--from={source_format}", f"--to={target_format}",
                "--sandbox", "--fail-if-warnings"]
        if target_format == "docx":
            args.extend(["-o", "-"])
        return await self._execute(args, data, deadline)

    async def _execute(self, args: list[str], data: bytes, deadline: float) -> bytes:
        if self._closed:
            raise AppError("DOCUMENT_EXPORT_UNAVAILABLE", "文档转换服务不可用", 503)
        if deadline <= asyncio.get_running_loop().time():
            raise AppError("DOCUMENT_EXPORT_TIMEOUT", "文档转换超时，请稍后重试", 504)
        operation = asyncio.current_task()
        self._operations.add(operation)
        spawn: asyncio.Task | None = None
        process = None
        pipes: list[asyncio.Task] = []
        try:
            async with asyncio.timeout_at(deadline):
                options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                # Windows 的 Uvicorn reload 使用 Selector loop，不支持 asyncio
                # subprocess transport。Popen 与阻塞管道在线程执行，保留异步调用契约。
                spawn = asyncio.create_task(asyncio.to_thread(
                    subprocess.Popen, args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, **options,
                ))
                process = await asyncio.shield(spawn)
                pipes = [
                    asyncio.create_task(asyncio.to_thread(self._write, process.stdin, data)),
                    asyncio.create_task(asyncio.to_thread(
                        self._read, process.stdout, limited=True,
                    )),
                    asyncio.create_task(asyncio.to_thread(
                        self._read, process.stderr, limited=False,
                    )),
                    asyncio.create_task(asyncio.to_thread(process.wait)),
                ]
                # 取消 await 不等于阻塞线程已结束；清理必须等待真实 I/O 返回。
                _, output, _, code = await asyncio.shield(asyncio.gather(*pipes))
                if code:
                    raise AppError("DOCUMENT_EXPORT_FAILED", "文档转换失败", 500)
                return output
        except TimeoutError as exc:
            raise AppError("DOCUMENT_EXPORT_TIMEOUT", "文档转换超时，请稍后重试", 504) from exc
        except OSError as exc:
            raise AppError("DOCUMENT_EXPORT_UNAVAILABLE", "文档转换程序无法启动", 503) from exc
        finally:
            try:
                await _settle(asyncio.create_task(self._cleanup(spawn, process, pipes)))
            finally:
                self._operations.discard(operation)

    def _read(self, stream, *, limited: bool) -> bytes:
        result = bytearray()
        limit = self._settings.document_export_max_output_bytes if limited else 8192
        while chunk := stream.read(65536):
            if limited and len(result) + len(chunk) > limit:
                raise AppError("EXPORT_OUTPUT_TOO_LARGE", "转换文档超过大小限制", 422)
            result.extend(chunk[:max(0, limit - len(result))])
        return bytes(result)

    @staticmethod
    def _write(stream, data: bytes) -> None:
        try:
            stream.write(data)
            stream.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stream.close()

    @staticmethod
    async def _cleanup(spawn, process, pipes) -> None:
        if process is None and spawn is not None:
            try:
                process = await spawn
            except (OSError, asyncio.CancelledError):
                pass
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            # 不取消 to_thread wrapper；杀死子进程后等待管道 EOF/写入失败。
            await asyncio.gather(*pipes, return_exceptions=True)
            await asyncio.to_thread(process.wait)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    async def aclose(self) -> None:
        self._closed = True
        tasks = list(self._operations - {asyncio.current_task()})
        for task in tasks:
            task.cancel()
        if tasks:
            await _settle(asyncio.create_task(self._join(tasks)))

    @staticmethod
    async def _join(tasks) -> None:
        await asyncio.gather(*tasks, return_exceptions=True)
