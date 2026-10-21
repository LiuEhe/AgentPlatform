import json


def test_content_is_removed_from_nested_export_and_errors():
    from app.infrastructure.langfuse.masking import mask_export

    data = {
        "input": {"messages": ["PRIVATE_DOCUMENT"]},
        "output": "PRIVATE_DOCUMENT",
        "metadata": {"run_id": "run-1", "arbitrary": "PRIVATE_DOCUMENT"},
        "exception": "PRIVATE_DOCUMENT",
        "status_message": "PRIVATE_DOCUMENT",
    }
    result = mask_export(data, capture_content=False, secrets=["CREDENTIAL"])
    assert "PRIVATE_DOCUMENT" not in json.dumps(result)
    assert result["metadata"]["run_id"] == "run-1"


def test_content_opt_in_never_exports_credentials():
    from app.infrastructure.langfuse.masking import mask_export

    result = mask_export(
        {
            "input": "hello CREDENTIAL",
            "authorization": "secret",
            "metadata": {"nested": {"api_key": "secret"}},
        },
        capture_content=True,
        secrets=["CREDENTIAL"],
    )
    text = json.dumps(result)
    assert "hello" in text
    assert "CREDENTIAL" not in text
    assert "secret" not in text
