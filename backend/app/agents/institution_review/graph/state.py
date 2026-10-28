"""制度审核 LangGraph 共享状态。"""

import operator
from typing import Annotated, TypedDict

from app.agents.institution_review.schemas import (
    ChunkReviewResult,
    Clause,
    ClauseReview,
    ReviewChunk,
    ReviewMode,
)
from app.schemas.review import ReviewReference


class ReviewState(TypedDict, total=False):
    """保存文档、拆分条款、审核结果和各章节 Markdown。"""

    review_id: str
    title: str
    document_title: str
    content: str
    review_mode: ReviewMode
    standard_name: str | None
    standard_content: str | None
    clauses: list[Clause]
    chunks: list[ReviewChunk]
    clause_reviews: list[ClauseReview]
    references: list[ReviewReference]
    reference_names: list[str]
    terminology_markdown: str
    overview_markdown: str
    conflict_markdown: str
    suggestion_markdown: str
    report_markdown: str


class ChunkReviewInput(TypedDict, total=False):
    """条款审核子图从父图读取的业务输入。"""

    title: str
    review_mode: ReviewMode
    clauses: list[Clause]
    chunks: list[ReviewChunk]
    standard_name: str | None
    standard_content: str | None


class ChunkWorkerState(TypedDict, total=False):
    """Send 的单组输入，不携带其他组或累计结果。"""

    title: str
    review_mode: ReviewMode
    chunk: ReviewChunk
    standard_name: str | None
    standard_content: str | None


class ChunkReviewOutput(TypedDict):
    """子图只向父图写入最终审核结果及引用。"""

    clause_reviews: list[ClauseReview]
    references: list[ReviewReference]


class ChunkReviewState(ChunkReviewInput, total=False):
    """每次调用独立的结果累积通道。"""

    chunk_results: Annotated[list[ChunkReviewResult], operator.add]
    clause_reviews: list[ClauseReview]
    references: list[ReviewReference]
