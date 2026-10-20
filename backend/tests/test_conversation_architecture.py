"""架构回归：验证本次明确要求的依赖边界与旧路径清理。"""

import ast
from pathlib import Path

APP = Path(__file__).parents[1] / "app"


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            result.append(node.module or "")
        elif isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
    return result


def test_agent_does_not_depend_on_services_or_store():
    for path in (APP / "agents" / "conversation_assistant").rglob("*.py"):
        assert not any(
            module.startswith(("app.services", "app.infrastructure.conversation"))
            for module in imports(path)
        ), path


def test_common_context_is_domain_independent():
    assert not any(
        module.startswith(("app.agents", "app.services"))
        for module in imports(APP / "nodes" / "llm" / "context.py")
    )


def test_store_does_not_import_http_views():
    assert "app.schemas.conversation" not in imports(
        APP / "infrastructure" / "conversation" / "in_memory_store.py"
    )
    assert "app.schemas.conversation" not in imports(APP / "schemas" / "conversation_session.py")


def test_service_has_no_private_agent_orchestration():
    assert not any(
        module.startswith("app.agents")
        for module in imports(APP / "services" / "conversation_service.py")
    )
    assert {path.name for path in (APP / "services").glob("conversation_*.py")} == {
        "conversation_service.py",
    }


def test_legacy_intent_entry_is_removed():
    assert not (APP / "agents" / "conversation_assistant" / "intent.py").exists()
