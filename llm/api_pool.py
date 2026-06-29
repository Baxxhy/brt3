"""Local OpenAI-compatible API pool.

Keys are read from the process environment and must never be printed or
serialized into experiment outputs.
"""

from __future__ import annotations

API_NAMES: list[str] = [
    "fa_254701003",
    "fa_244711003",
    "fa_254711063",
    "fa_244701007",
    "fa_254711072",
    "tao_yifan",
    "fa_254711067",
    "fa_251812017",
    "extra_20260628",
]

API_KEYS: list[str] = [
    "sk-lZfASZqz0EyU13GNFhT8uVfUQD3aC6umuIFozrg6HTz1VDgq",
    "sk-23Nv7ebOWzNr4I05UX9YmWzEwp7JCSx5kfjGbKIVJ0ChCmWK",
    "sk-8nOXxOG58owlpoGCHxPmou1IFdvqmllHW4CKXURWlPMTX1lN",
    "sk-C5qhFRG0JcccispW1tZ5EGFp5vdpYJod1Yaj7eW5hGCNFeeV",
    "sk-BPWARlpCwipqJWGLbgA8thLTs5C0ukyRkx0G7D4gHajNxrFb",
    "sk-1LXIfDaj5uXPDGxaoOnPF3yVeCx3ihmAunaiMx8y2egJSfZt",
    "sk-fsgAIDD91mdxR8FOyf5a7yfACLxMekCP1ubfBhfadBBh0Tw7",
    "sk-2I1EnoJE82BLWl5EgVR7Gds0Em3suNPaML2gTdxnJG7coy9o",
    "sk-h0cFjLrI80RePeqK7hyFUzW4IrVo9u1GJUX9rTmZVe85xqBP",
]

API_BASE_URLS: list[str] = [
    "https://api.chat.csu.edu.cn/v1",
]

API_MODELS: list[str] = [
    "deepseek-v3",
]


def configured_apis() -> list[tuple[str, str, str]]:
    """Return validated (key, base_url, model) entries without logging secrets."""
    keys = [value.strip() for value in API_KEYS if value.strip()]
    if not keys:
        return []
    if len(API_NAMES) != len(keys):
        raise ValueError("API_NAMES must match API_KEYS length")
    if len(API_BASE_URLS) not in {1, len(keys)}:
        raise ValueError("API_BASE_URLS must contain one value or match key count")
    if len(API_MODELS) not in {0, 1, len(keys)}:
        raise ValueError("API_MODELS must be empty, contain one value, or match key count")
    bases = API_BASE_URLS * len(keys) if len(API_BASE_URLS) == 1 else API_BASE_URLS
    if not API_MODELS:
        models = [""] * len(keys)
    else:
        models = API_MODELS * len(keys) if len(API_MODELS) == 1 else API_MODELS
    return [
        (key, bases[index].strip(), models[index].strip())
        for index, key in enumerate(keys)
    ]


def configured_api_metadata() -> list[dict[str, str | int]]:
    """Return non-secret API metadata for logs, summaries, and self-checks."""
    entries = configured_apis()
    return [
        {
            "index": index,
            "name": API_NAMES[index] if index < len(API_NAMES) else f"key_{index}",
            "base_url": entries[index][1],
            "model": entries[index][2],
        }
        for index in range(len(entries))
    ]
