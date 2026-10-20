"""制度审核的能力说明、原文参数映射与受限运行时调用。"""

import re
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from app.agents.conversation_assistant.config import ConversationAgentConfig
from app.agents.conversation_assistant.nodes.material_prepare import resolve_material
from app.agents.conversation_assistant.schemas import PreparedReview, ReviewArguments
from app.agents.institution_review.schemas import ReviewMode
from app.core.errors import AppError
from app.runtime.agent_runtime import AgentInvoker
from app.schemas.conversation_turn import ChildAgentResult


def review_capabilities(config: ConversationAgentConfig) -> list[dict[str, object]]:
    return [
        {
            "agent_id": "institution_review",
            "name": "制度审核助手",
            "description": "仅执行制度草稿审核，不用于一般问答、闲聊、摘要或其他领域的文字审核",
            "modes": ["standard_document", "knowledge_base"],
            "knowledge_base_configured": config.knowledge_base_configured,
            "parameters": (
                "draft/standard 为 document 或 user_message 的材料引用；必须明确 review_mode"
            ),
        }
    ]


def prepare_review(
    args: ReviewArguments,
    materials: Mapping[tuple[str, str], tuple[str, str]],
    config: ConversationAgentConfig,
) -> PreparedReview | str:
    if args.draft is None:
        return "请提供需要审核的制度草稿，可以粘贴正文或上传 DOCX。"
    if args.review_mode is None:
        return "请确认使用知识库审核，还是提供标准文档进行对比审核？"
    if args.review_mode == ReviewMode.STANDARD_DOCUMENT and args.standard is None:
        return "请提供对比标准，可以粘贴标准正文或上传 DOCX，并说明哪份是标准。"
    if args.review_mode == ReviewMode.KNOWLEDGE_BASE:
        if args.standard is not None:
            return "知识库模式不能同时附带标准，请确认审核方式。"
        if not config.knowledge_base_configured:
            return "知识库审核尚未配置，可提供标准材料后使用对比审核。"
    if args.standard == args.draft:
        return "草稿与标准引用相同，请确认两份材料的角色。"
    filename, markdown = resolve_material(materials, args.draft)
    if not markdown.strip() or len(markdown) > config.max_review_chars:
        raise AppError("INVALID_REVIEW_INPUT", "草稿正文为空或超过审核限制", 422)
    match = re.search(r"^\s{0,3}#\s+(.+?)\s*$", markdown, re.MULTILINE)
    original_title = match.group(1).strip() if match else ""
    if re.match(r"^第[一二三四五六七八九十百千万零〇两0-9]+(?:章|节|条)", original_title):
        original_title = ""
    title = " ".join((original_title or Path(filename).stem).split())[:200] or "未命名制度"
    payload: dict[str, object] = {
        "title": title,
        "content": markdown,
        "review_mode": args.review_mode.value,
    }
    if original_title and original_title != title:
        payload["document_title"] = original_title
    if args.standard:
        name, text = resolve_material(materials, args.standard)
        if not text.strip() or len(text) > config.max_review_chars:
            raise AppError("INVALID_REVIEW_INPUT", "标准正文为空或超过审核限制", 422)
        payload.update(standard_name=name, standard_content=text)
    return PreparedReview(payload=payload)


async def invoke_review(invoke_agent: AgentInvoker, prepared: PreparedReview) -> ChildAgentResult:
    prepared = PreparedReview.model_validate(prepared.model_dump())
    execution = await invoke_agent(prepared.agent_id, prepared.payload)
    if not isinstance(execution.output, str) or not execution.output.strip():
        raise AppError("AGENT_OUTPUT_INVALID", "子智能体未返回可展示结果", 502)
    if len(execution.output) > 200000:
        raise AppError("AGENT_OUTPUT_TOO_LARGE", "子智能体输出超过展示限制", 502)
    return ChildAgentResult(
        id=str(uuid4()),
        agent_id="institution_review",
        agent_name="制度审核助手",
        invocation_id=execution.invocation_id,
        output_type="markdown",
        output=execution.output,
    )
