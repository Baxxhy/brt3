"""OpenAI-compatible DeepSeek client."""

from __future__ import annotations

import json
import os
import hashlib
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from llm.api_pool import API_NAMES, configured_apis
from core.config import (
    DEFAULT_LLM_BACKOFF_BASE,
    DEFAULT_LLM_MAX_ATTEMPTS,
    DEFAULT_LLM_RATE_LIMIT_BACKOFF,
    DEFAULT_LLM_REQUEST_TIMEOUT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    load_llm_config,
)


class LLMClient:
    _key_lock = threading.Lock()
    _key_index = 0

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        instance_id: str = "",
        llm_cache_dir: str = "",
        reuse_llm_cache: bool = True,
        refresh_llm_cache: bool = False,
        deterministic: bool = True,
    ) -> None:
        cfg = load_llm_config(model=model, api_key=api_key, base_url=base_url, temperature=temperature, max_tokens=max_tokens)
        self.model = cfg.model or DEFAULT_MODEL
        self._uses_local_pool = False
        self.instance_id = instance_id
        self.llm_cache_dir = Path(llm_cache_dir) if llm_cache_dir else None
        self.reuse_llm_cache = reuse_llm_cache
        self.refresh_llm_cache = refresh_llm_cache
        self.deterministic = deterministic
        self.cache_hit_count = 0
        self.cache_miss_count = 0
        self.api_retry_count = 0
        self.api_error_types: list[str] = []
        self.selected_key_index = -1
        self.selected_key_name = ""
        local_api = self._pick_local_api(instance_id) if not api_key else None
        if local_api:
            local_index, local_key, local_base, local_model = local_api
            self.api_key = local_key
            self.base_url = (local_base or cfg.base_url or "https://api.deepseek.com").rstrip("/")
            self.model = local_model or self.model
            self._uses_local_pool = True
            self.selected_key_index = local_index
            self.selected_key_name = API_NAMES[local_index] if local_index < len(API_NAMES) else f"key_{local_index}"
        else:
            multi_key = self._pick_env_key() if not api_key else None
            self.api_key = api_key or multi_key or cfg.api_key
            self.base_url = (cfg.base_url or "https://api.deepseek.com").rstrip("/")
        self.temperature = cfg.temperature
        self.max_tokens = cfg.max_tokens
        self.request_timeout = int(
            os.environ.get("BRT3_LLM_REQUEST_TIMEOUT", DEFAULT_LLM_REQUEST_TIMEOUT)
        )
        self.max_attempts = int(
            os.environ.get("BRT3_LLM_MAX_ATTEMPTS", DEFAULT_LLM_MAX_ATTEMPTS)
        )
        self.backoff_base = float(
            os.environ.get("BRT3_LLM_BACKOFF_BASE", DEFAULT_LLM_BACKOFF_BASE)
        )
        self.rate_limit_backoff = float(
            os.environ.get(
                "BRT3_LLM_RATE_LIMIT_BACKOFF",
                DEFAULT_LLM_RATE_LIMIT_BACKOFF,
            )
        )
        if not self.api_key:
            raise ValueError("missing API key; set DEEPSEEK_API_KEY or OPENAI_API_KEY")

    @classmethod
    def _stable_index(cls, instance_id: str, size: int) -> int:
        if size <= 0:
            return 0
        if not instance_id:
            with cls._key_lock:
                index = cls._key_index % size
                cls._key_index += 1
                return index
        digest = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()
        return int(digest[:12], 16) % size

    @classmethod
    def _pick_local_api(cls, instance_id: str = "", offset: int = 0) -> tuple[int, str, str, str] | None:
        entries = configured_apis()
        if not entries:
            return None
        index = (cls._stable_index(instance_id, len(entries)) + offset) % len(entries)
        entry = entries[index]
        return index, entry[0], entry[1], entry[2]

    @classmethod
    def _env_keys(cls) -> list[str]:
        raw = os.environ.get("DEEPSEEK_API_KEYS") or ""
        return [x.strip() for x in raw.split(",") if x.strip()]

    @classmethod
    def _pick_env_key(cls) -> str | None:
        keys = cls._env_keys()
        if not keys:
            return None
        with cls._key_lock:
            key = keys[cls._key_index % len(keys)]
            cls._key_index += 1
        return key

    def _rotate_api(self) -> None:
        if self._uses_local_pool:
            next_offset = 1
            if self.selected_key_index >= 0:
                base = self._stable_index(self.instance_id, len(configured_apis()))
                next_offset = (self.selected_key_index - base + 1) % max(1, len(configured_apis()))
            entry = self._pick_local_api(self.instance_id, next_offset)
            if entry:
                index, self.api_key, base_url, local_model = entry
                self.base_url = (base_url or self.base_url).rstrip("/")
                if local_model:
                    self.model = local_model
                self.selected_key_index = index
                self.selected_key_name = API_NAMES[index] if index < len(API_NAMES) else f"key_{index}"
                return
        rotated = self._pick_env_key()
        if rotated:
            self.api_key = rotated

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_key(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        stage_name: str,
        response_format: str,
    ) -> str:
        parts = {
            "model": self.model,
            "temperature": temperature,
            "response_format": response_format,
            "stage_name": stage_name,
            "system_prompt_sha256": self._sha(system_prompt),
            "user_prompt_sha256": self._sha(user_prompt),
        }
        raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
        return self._sha(raw)

    def _cache_path(self, cache_key: str) -> Path | None:
        if self.llm_cache_dir is None:
            return None
        return self.llm_cache_dir / cache_key[:2] / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> str | None:
        if self.refresh_llm_cache or not self.reuse_llm_cache:
            return None
        path = self._cache_path(cache_key)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            response = data.get("response_text")
        except Exception:
            return None
        if isinstance(response, str):
            self.cache_hit_count += 1
            return response
        return None

    def _write_cache(
        self,
        cache_key: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        stage_name: str,
        response_text: str,
    ) -> None:
        path = self._cache_path(cache_key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        base_hash = self._sha(self.base_url)[:16]
        data = {
            "model": self.model,
            "temperature": temperature,
            "stage_name": stage_name,
            "instance_id": self.instance_id,
            "system_prompt_sha256": self._sha(system_prompt),
            "user_prompt_sha256": self._sha(user_prompt),
            "response_text": response_text,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "selected_key_index": self.selected_key_index,
            "selected_key_name": self.selected_key_name,
            "api_base_hash": base_hash,
            "cache_key": cache_key,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def stats(self) -> dict[str, object]:
        return {
            "llm_cache_hit_count": self.cache_hit_count,
            "llm_cache_miss_count": self.cache_miss_count,
            "selected_key_index": self.selected_key_index,
            "selected_key_name": self.selected_key_name,
            "api_retry_count": self.api_retry_count,
            "api_error_types": list(dict.fromkeys(self.api_error_types)),
        }

    @staticmethod
    def _chat_url(base_url: str) -> str:
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            return url + "/chat/completions"
        if not url.endswith("/v1/chat/completions") and not url.endswith("/chat/completions"):
            return url + "/v1/chat/completions"
        return url

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stage_name: str = "default",
        response_format: str = "text",
    ) -> str:
        effective_temperature = self.temperature if temperature is None else temperature
        cache_key = self._cache_key(
            system_prompt,
            user_prompt,
            effective_temperature,
            stage_name,
            response_format,
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        self.cache_miss_count += 1
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": effective_temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        last_error: Exception | None = None
        max_attempts = max(
            self.max_attempts,
            len(configured_apis()),
            len(self._env_keys()),
        )
        for attempt in range(max_attempts):
            payload["model"] = self.model
            data = json.dumps(payload).encode("utf-8")
            url = self._chat_url(self.base_url)
            headers["Authorization"] = f"Bearer {self.api_key}"
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:  # noqa: S310
                    body = resp.read().decode("utf-8")
                parsed = json.loads(body)
                response_text = parsed["choices"][0]["message"]["content"]
                self._write_cache(
                    cache_key,
                    system_prompt,
                    user_prompt,
                    effective_temperature,
                    stage_name,
                    response_text,
                )
                return response_text
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"LLM HTTP {exc.code}: {body[:500]}")
                self.api_retry_count += 1
                self.api_error_types.append(f"HTTP_{exc.code}")
                if exc.code in {401, 403, 429}:
                    self._rotate_api()
                if exc.code == 429 and attempt < max_attempts - 1:
                    retry_after = exc.headers.get("Retry-After")
                    try:
                        server_wait = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        server_wait = 0.0
                    wait = max(
                        server_wait,
                        min(self.rate_limit_backoff * (2**attempt), 300.0),
                    )
                    time.sleep(wait)
                    continue
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self.api_retry_count += 1
                self.api_error_types.append(type(exc).__name__)
                self._rotate_api()
            if attempt < max_attempts - 1:
                time.sleep(min(self.backoff_base * (2**attempt), 180.0))
        raise RuntimeError(f"LLM request failed after {max_attempts} attempts: {last_error}")
