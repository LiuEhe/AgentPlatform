import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.document_export import DocumentExportRequest


def test_export_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.document_export_timeout_seconds == 30
    assert settings.document_export_concurrency == 2
    assert settings.document_export_max_chars == 200000
    assert settings.document_export_max_body_bytes == 1048576
    assert settings.document_export_max_output_bytes == 10485760


@pytest.mark.parametrize('field', [
    'document_export_timeout_seconds', 'document_export_concurrency',
    'document_export_max_chars', 'document_export_max_body_bytes',
    'document_export_max_output_bytes',
])
@pytest.mark.parametrize('value', [0, -1])
def test_export_settings_reject_nonpositive_limits(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_export_request_preserves_indentation():
    markdown = '  正文\n\n    code\n'
    assert DocumentExportRequest(markdown=markdown).markdown == markdown
    assert DocumentExportRequest(markdown='文' * 200000, title='题' * 200)


@pytest.mark.parametrize('fields', [
    {}, {'markdown': ''}, {'markdown': ' \n'}, {'markdown': 1},
    {'markdown': '文', 'title': None}, {'markdown': '文', 'title': ' '},
    {'markdown': '文', 'title': '题' * 201}, {'markdown': '文', 'title': '题\r\n'},
    {'markdown': '文', 'title': '\x7f'}, {'markdown': '文' * 200001},
    {'markdown': '文', 'output_path': 'ignored'},
])
def test_export_request_rejects_invalid_fields(fields):
    with pytest.raises(ValidationError):
        DocumentExportRequest.model_validate(fields)


def test_config_cannot_exceed_http_character_contract():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, document_export_max_chars=200001)
