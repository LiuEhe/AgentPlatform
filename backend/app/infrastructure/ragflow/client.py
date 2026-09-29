"""封装 RAGFlow 知识片段检索 API。"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class RetrievedChunk:
    """从 RAGFlow 归一化后的知识片段。"""

    content: str
    document_name: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    similarity: float | None = None


class RagFlowClient:
    """通过 RAGFlow REST API 检索指定知识库。"""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def retrieve(self, query: str, *, top_k: int = 8) -> list[RetrievedChunk]:
        """检索知识片段并兼容 RAGFlow 字典或列表格式的 chunks。"""
        if not self._settings.ragflow_base_url or not self._settings.ragflow_api_key:
            raise AppError("RAGFLOW_NOT_CONFIGURED", "RAGFlow 配置不完整", 503)
        if not self._settings.ragflow_dataset_id:
            raise AppError("RAGFLOW_NOT_CONFIGURED", "RAGFlow 知识库 ID 未配置", 503)

        try:
            response = await self._client.post(
                f"{self._settings.ragflow_base_url}/api/v1/retrieval",
                headers={"Authorization": f"Bearer {self._settings.ragflow_api_key}"},
                json={
                    "question": query,
                    "dataset_ids": [self._settings.ragflow_dataset_id],
                    "page": 1,
                    "page_size": top_k,
                    "knn_top_k": max(top_k, 32),
                    "keyword": True,
                    "highlight": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise AppError("RAGFLOW_TIMEOUT", "知识检索服务响应超时", 503) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError("RAGFLOW_ERROR", "知识检索服务请求失败", 502) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("RAGFLOW_ERROR", "无法读取知识检索服务响应", 502) from exc

        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise AppError("RAGFLOW_ERROR", "知识检索服务返回错误", 502)

        data = payload.get("data") or {}
        raw_chunks: Any = data.get("chunks", []) if isinstance(data, dict) else []
        if isinstance(raw_chunks, dict):
            raw_chunks = list(raw_chunks.values())
        if not isinstance(raw_chunks, list):
            raise AppError("RAGFLOW_ERROR", "知识检索结果格式无效", 502)

        chunks: list[RetrievedChunk] = []
        for item in raw_chunks:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            similarity = item.get("similarity")
            document_name = item.get("document_name") or item.get("document_keyword")
            chunks.append(
                RetrievedChunk(
                    content=content,
                    document_name=document_name if isinstance(document_name, str) else None,
                    document_id=item.get("document_id"),
                    chunk_id=item.get("id"),
                    url=item.get("url"),
                    similarity=(
                        float(similarity) if isinstance(similarity, (float, int)) else None
                    ),
                )
            )
        return chunks[:top_k]
