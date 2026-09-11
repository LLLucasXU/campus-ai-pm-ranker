"""Safe local persistence for generic collection recipes and checkpoints."""

from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import time
from typing import Any, Mapping, Optional

from .collection import CollectionCheckpoint, SiteRecipe


class SensitiveCollectionDataError(ValueError):
    """Raised before potentially credential-like collection data is persisted."""


_SENSITIVE_KEYWORDS = ("authorization", "cookie", "token", "password", "secret", "credential")


def _assert_non_sensitive(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(keyword in key_text for keyword in _SENSITIVE_KEYWORDS):
                raise SensitiveCollectionDataError(f"禁止持久化敏感采集字段: {path}.{key}")
            _assert_non_sensitive(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_non_sensitive(child, f"{path}[{index}]")


class CollectionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.recipes_dir = root / "site-recipes"
        self.checkpoints_dir = root / "collection-checkpoints"
        self.cache_dir = root / "collection-cache"

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        _assert_non_sensitive(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def save_recipe(self, recipe: SiteRecipe) -> Path:
        path = self.recipes_dir / f"{self._safe_name(recipe.host)}.json"
        self._write_json(path, asdict(recipe))
        return path

    def load_recipe(self, host: str) -> Optional[SiteRecipe]:
        path = self.recipes_dir / f"{self._safe_name(host)}.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        _assert_non_sensitive(payload)
        return SiteRecipe(
            host=str(payload["host"]),
            recipe_id=str(payload["recipe_id"]),
            capabilities=dict(payload.get("capabilities", {})),
        )

    def save_checkpoint(self, run_id: str, checkpoint: CollectionCheckpoint) -> Path:
        path = self.checkpoints_dir / f"{self._safe_name(run_id)}.json"
        self._write_json(path, asdict(checkpoint))
        return path

    def load_checkpoint(self, run_id: str) -> Optional[CollectionCheckpoint]:
        path = self.checkpoints_dir / f"{self._safe_name(run_id)}.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        _assert_non_sensitive(payload)
        return CollectionCheckpoint(
            career_url=str(payload["career_url"]),
            page_number=int(payload.get("page_number", 1)),
            cursor=str(payload.get("cursor", "")),
            seen_job_ids=tuple(str(item) for item in payload.get("seen_job_ids", [])),
        )

    def save_cache_entry(self, cache_key: str, payload: Mapping[str, Any], ttl_seconds: int) -> Path:
        """保存短期可复用的非敏感采集结果，不保存网页会话或正文。"""

        if not cache_key.strip():
            raise ValueError("缓存键不能为空")
        if ttl_seconds <= 0:
            raise ValueError("缓存有效期必须大于零")
        digest = sha256(cache_key.encode("utf-8")).hexdigest()
        now = int(time())
        path = self.cache_dir / f"{digest}.json"
        self._write_json(
            path,
            {
                "cache_key": cache_key,
                "stored_at_unix": now,
                "expires_at_unix": now + ttl_seconds,
                "payload": dict(payload),
            },
        )
        return path

    def load_cache_entry(self, cache_key: str, *, now_unix: Optional[int] = None) -> Optional[Mapping[str, Any]]:
        """读取未过期且通过敏感字段检查的缓存；过期内容视为未命中。"""

        digest = sha256(cache_key.encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{digest}.json"
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        _assert_non_sensitive(raw)
        current = int(time()) if now_unix is None else int(now_unix)
        if int(raw.get("expires_at_unix", 0)) <= current:
            return None
        payload = raw.get("payload")
        if not isinstance(payload, Mapping):
            return None
        return dict(payload)
