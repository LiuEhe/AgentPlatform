"""Langfuse 远端 Prompt 读取；本地模板及参数校验仍由调用方定义。"""

import asyncio
import logging

from langchain_core.prompts import ChatPromptTemplate

from app.nodes.llm.prompts import PromptResolver, ResolvedPrompt

logger = logging.getLogger(__name__)


class LangfusePromptResolver(PromptResolver):
    def __init__(self, client, *, label="production", cache_ttl_seconds=60):
        self.client = client
        self.label = label
        self.cache_ttl_seconds = cache_ttl_seconds

    async def _resolve(self, spec, *, version, strict):
        try:
            remote = await asyncio.to_thread(
                self.client.get_prompt,
                spec.name,
                type="chat",
                cache_ttl_seconds=self.cache_ttl_seconds,
                **({"version": version} if version is not None else {"label": self.label}),
            )
            template = ChatPromptTemplate.from_messages(remote.get_langchain_prompt())
            local = ChatPromptTemplate.from_messages(spec.messages)
            if template.input_variables != local.input_variables:
                raise ValueError("PROMPT_VARIABLE_MISMATCH")
            if [m.prompt.template for m in template.messages if hasattr(m, "prompt")] == []:
                raise ValueError("PROMPT_MESSAGES_INVALID")
            template.metadata = {
                "langfuse_prompt": remote,
                "fallback": False,
                "prompt_name": spec.name,
                "prompt_version": remote.version,
            }
            return ResolvedPrompt(template, spec.name, remote.version, False)
        except Exception as exc:
            logger.warning(
                "prompt_fallback prompt_name=%s error_type=%s", spec.name, type(exc).__name__
            )
            if strict:
                raise ValueError("PROMPT_VERSION_UNAVAILABLE") from None
            return await super()._resolve(spec, version=None, strict=False)
