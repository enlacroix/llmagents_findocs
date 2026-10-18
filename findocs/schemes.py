import json
from functools import cache

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from findocs import config

DEFAULT_SCHEME = "default_scheme.json"


@cache
def _schemes() -> dict[str, dict]:
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in config.SCHEMES_DIR.glob("*.json")}


@cache
def _registry() -> Registry:
    return Registry().with_resources((name, Resource.from_contents(s)) for name, s in _schemes().items())


def document_types() -> list[str]:
    return _schemes()[DEFAULT_SCHEME]["properties"]["document_type"]["enum"]


def scheme_for(document_type: str) -> str:
    for name, schema in _schemes().items():
        if schema.get("properties", {}).get("document_type", {}).get("const") == document_type:
            return name
    return DEFAULT_SCHEME


def prompt_text(scheme: str) -> str:
    parts = [] if scheme == DEFAULT_SCHEME else [f"// {scheme}\n" + json.dumps(_schemes()[scheme], ensure_ascii=False)]
    parts.append(f"// {DEFAULT_SCHEME}\n" + json.dumps(_schemes()[DEFAULT_SCHEME], ensure_ascii=False))
    return "\n\n".join(parts)


def validate(data: dict, scheme: str) -> list[str]:
    schema = _schemes()[scheme]
    if scheme == DEFAULT_SCHEME:
        schema = {"allOf": [{"$ref": DEFAULT_SCHEME}], "unevaluatedProperties": False}
    validator = Draft202012Validator(schema, registry=_registry())
    return [
        f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    ]
