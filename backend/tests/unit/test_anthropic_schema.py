"""Anthropic structured-output schema sanitisation."""

from __future__ import annotations

from app.clients.llm.anthropic_provider import _sanitize_schema


def test_sanitize_strips_unsupported_validation_keywords():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 3,
                "minItems": 1,
                "items": {"type": "string", "maxLength": 5, "minLength": 1},
            },
            "count": {"type": "integer", "minimum": 0, "maximum": 10},
            # A property literally named "format" must survive.
            "format": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    out = _sanitize_schema(schema)

    assert "maxItems" not in out["properties"]["items"]
    assert "minItems" not in out["properties"]["items"]
    assert "maxLength" not in out["properties"]["items"]["items"]
    assert "minLength" not in out["properties"]["items"]["items"]
    assert "minimum" not in out["properties"]["count"]
    assert "maximum" not in out["properties"]["count"]
    # The "format" property definition is untouched; only the keyword family is stripped.
    assert out["properties"]["format"]["enum"] == ["a", "b"]
    # Structural keywords are preserved.
    assert out["required"] == ["items"]
    assert out["additionalProperties"] is False
    assert out["properties"]["items"]["type"] == "array"
