"""Межпроцессный кэш вычисленных агрегатов оценок (Redis).

Инвалидация — версионная: каждая запись GradeReport (upload с десктопа,
редактирование учеников) увеличивает счётчик версии школы, и все ключи,
собранные под старой версией, перестают читаться (протухают по TTL).

Без Redis кэширование прозрачно отключается: builder просто выполняется —
межпроцессная инвалидация в fallback-режиме невозможна, а устаревшая
аналитика хуже, чем медленная.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from ...redis_utils import get_redis_client

_VERSION_KEY = "grade_reports:ver:{school_id}"
_CACHE_KEY = "grade_reports:cache:{school_id}:v{version}:{name}:{params_hash}"

DEFAULT_TTL_SECONDS = 30 * 60


def bump_grade_reports_version(school_id: int) -> None:
    """Инвалидировать кэш школы (вызывается при любой записи GradeReport)."""
    client = get_redis_client()
    if not client:
        return
    try:
        client.incr(_VERSION_KEY.format(school_id=school_id))
    except Exception:
        pass


def _get_version(client: Any, school_id: int) -> str:
    try:
        return client.get(_VERSION_KEY.format(school_id=school_id)) or "0"
    except Exception:
        return "0"


def cached_computation(
    school_id: int,
    name: str,
    params: dict[str, Any],
    builder: Callable[[], Any],
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Any:
    """Вернуть результат builder() из Redis-кэша или вычислить и закэшировать.

    Результат должен быть JSON-сериализуемым (dict/list/скаляры).
    """
    client = get_redis_client()
    if not client:
        return builder()

    params_hash = hashlib.md5(
        json.dumps(params, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    key = _CACHE_KEY.format(
        school_id=school_id,
        version=_get_version(client, school_id),
        name=name,
        params_hash=params_hash,
    )

    try:
        cached = client.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass

    result = builder()

    try:
        client.setex(key, ttl_seconds, json.dumps(result, ensure_ascii=False))
    except (TypeError, ValueError):
        # Результат не JSON-сериализуем — не кэшируем, но и не ломаем вызов
        pass
    except Exception:
        pass

    return result
