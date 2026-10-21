"""显式初始化缺失 Prompt；冲突不覆盖，已有标签不移动。"""

import argparse
import asyncio
import json
import re

from app.agents.conversation_assistant.prompts import CONVERSATION_PROMPTS
from app.agents.institution_review.prompts import REVIEW_PROMPTS
from app.core.config import Settings
from app.infrastructure.langfuse.client import create_observer, shutdown_observer


def prompt_specs():
    return [*CONVERSATION_PROMPTS.values(), *REVIEW_PROMPTS.values()]


def sync_prompts(*, client, apply: bool, initial_label: str | None = None):
    summary = dict(created=0, missing=0, unchanged=0, conflict=0)
    for spec in prompt_specs():
        try:
            remote = client.get_prompt(spec.name, type="chat", label="latest", cache_ttl_seconds=0)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            if not apply:
                summary["missing"] += 1
                continue
            client.create_prompt(
                name=spec.name,
                type="chat",
                labels=[initial_label] if initial_label else [],
                prompt=[
                    {
                        "role": "user" if role == "human" else role,
                        "content": re.sub(r"\{([a-z_]\w*)\}", r"{{\1}}", text),
                    }
                    for role, text in spec.messages
                ],
            )
            summary["created"] += 1
            continue
        actual = tuple(
            ("human" if role == "user" else role, text)
            for role, text in remote.get_langchain_prompt()
        )
        summary["unchanged" if actual == spec.messages else "conflict"] += 1
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--initial-label", help="仅用于新建模板；不会移动已有标签")
    args = parser.parse_args(argv)
    observer = create_observer(Settings())
    try:
        if not hasattr(observer, "client"):
            raise ValueError("LANGFUSE_NOT_CONFIGURED")
        result = sync_prompts(
            client=observer.client, apply=args.apply, initial_label=args.initial_label
        )
        print(json.dumps(result))
        return 1 if result["conflict"] else 0
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}))
        return 1
    finally:
        asyncio.run(shutdown_observer(observer))


if __name__ == "__main__":
    raise SystemExit(main())
