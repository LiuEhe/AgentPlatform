"""公共 DOCX 解析入口：格式边界检查与现有转换器复用。"""

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from app.nodes.document.docx_to_markdown import DocumentReadError, convert_docx_to_markdown


class DocumentParseError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def parse_docx(
    content: bytes,
    *,
    max_chars: int,
    max_archive_entries: int = 2000,
    max_uncompressed_bytes: int = 104857600,
) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > max_archive_entries
                or sum(entry.file_size for entry in entries) > max_uncompressed_bytes
            ):
                raise DocumentParseError("UPLOAD_TOO_LARGE", "文档解压内容超过限制")
        markdown = convert_docx_to_markdown(content)
    except DocumentParseError:
        raise
    except (BadZipFile, DocumentReadError, ValueError) as exc:
        raise DocumentParseError("INVALID_DOCX", "文档无法读取或不含有效文字") from exc
    if len(markdown) > max_chars:
        raise DocumentParseError("REVIEW_CONTENT_TOO_LONG", "文档正文超过限制")
    return markdown
