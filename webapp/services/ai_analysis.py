"""Единый сервис генерации ИИ-анализа суммативного оценивания (СОР/СОЧ) через Qwen/DashScope."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from ..models import School, User

logger = logging.getLogger(__name__)

DEFAULT_AI_MODEL = "qwen-flash-character"
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

SYSTEM_PROMPT = """Ты помощник учителя в Казахстане. Генерируй анализ суммативного оценивания (15-30 слов на поле).

ЯЗЫК ОТВЕТА: Сначала определи язык входных данных пользователя (казахский или русский). Отвечай СТРОГО на том же языке, на котором написаны цели обучения. Если цели на казахском — весь JSON на казахском. Если на русском — весь JSON на русском. Никогда не смешивай языки.

СТРОГО РАЗЛИЧАЙ три поля:

"difficulties_list" = ЧТО НЕ ПОЛУЧИЛОСЬ (какие темы/задания вызвали трудности)
Пример (рус): "Учащиеся допускали ошибки при решении уравнений с дробями и построении графиков линейных функций."
Пример (каз): "Оқушылар бөлшектермен теңдеулерді шешу және сызықтық функциялар графиктерін тұрғызу кезінде қателіктер жіберді."

"reasons" = ПОЧЕМУ НЕ ПОЛУЧИЛОСЬ (причины затруднений)
Пример (рус): "Слабо усвоены правила работы с дробями, недостаточно практики в построении координатных систем."
Пример (каз): "Бөлшектермен жұмыс ережелері нашар меңгерілген, координаталық жүйелерді тұрғызу бойынша тәжірибе жеткіліксіз."

"correction" = ЧТО ДЕЛАТЬ (план коррекционной работы)
Пример (рус): "Провести повторение темы 'Дроби', выполнить тренировочные упражнения по построению графиков."
Пример (каз): "'Бөлшектер' тақырыбын қайталау, графиктерді тұрғызу бойынша жаттығу жұмыстарын орындау."

JSON формат: {"difficulties_list": "...", "reasons": "...", "correction": "..."}"""

_KK_CHARS = frozenset("әғқңөұүһіӘҒҚҢӨҰҮҺІ")


def resolve_school_ai_credentials(user_or_school: User | School | None) -> tuple[str | None, str]:
    """Возвращает (api_key, ai_model) для пользователя или школы с резервом на DASHSCOPE_API_KEY."""
    school: School | None = None
    if isinstance(user_or_school, School):
        school = user_or_school
    elif isinstance(user_or_school, User):
        school = user_or_school.school

    api_key: str | None = None
    ai_model = DEFAULT_AI_MODEL
    if school:
        if school.ai_api_key and school.ai_api_key != "sk-xxx":
            api_key = school.ai_api_key
        if school.ai_model:
            ai_model = school.ai_model

    if not api_key:
        env_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        if env_key and env_key != "sk-xxx":
            api_key = env_key

    return api_key, ai_model


def build_user_prompt(achieved: str, difficulties: str) -> str:
    return f"""Цели обучения:

Достигнутые: {achieved or 'Не указаны'}

С затруднениями: {difficulties}

Заполни JSON:
- difficulties_list: перечисли ЧТО не получилось
- reasons: объясни ПОЧЕМУ не получилось  
- correction: напиши ЧТО ДЕЛАТЬ для исправления"""


def parse_ai_json_response(content: str | None) -> dict[str, Any] | None:
    """Разбирает JSON-ответ от модели (поддерживает чистый JSON и блок внутри текста)."""
    if not content:
        return None
    text = content.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def generate_fallback_analysis_dict(
    achieved: str,
    difficulties: str,
    error: str | None = None,
) -> dict[str, Any]:
    """Шаблонная генерация анализа (RU / KK), когда AI API недоступен."""
    combined = (difficulties or "") + (achieved or "")
    is_kk = any(c in _KK_CHARS for c in combined)

    diff_lines = [line.strip() for line in (difficulties or "").split("\n") if line.strip()][:3]
    diff_summary = "; ".join(line.lstrip("0123456789.-* ") for line in diff_lines).lower()

    if is_kk:
        difficulties_list = (
            f"Оқушылар мынадай тақырыптар бойынша тапсырмаларды орындау кезінде қиындықтар көрді: {diff_summary}."
            if diff_summary
            else ""
        )
        reasons = (
            "Теориялық білімді практикада қолдану дағдылары жеткіліксіз қалыптасқан. "
            "Материалды бекіту бойынша қосымша жұмыс қажет."
        )
        correction = (
            "Білімдегі олқылықтарды жою үшін жеке кеңестер өткізу. "
            "Теориялық материалды қайталау және практикалық жаттығуларды орындау."
        )
    else:
        difficulties_list = (
            f"Обучающиеся испытывали затруднения при выполнении заданий по темам: {diff_summary}."
            if diff_summary
            else ""
        )
        reasons = (
            "Недостаточно сформированы навыки применения теоретических знаний на практике. "
            "Требуется дополнительная работа над закреплением материала."
        )
        correction = (
            "Провести индивидуальные консультации для устранения пробелов в знаниях. "
            "Повторить теоретический материал и выполнить практические упражнения."
        )

    payload: dict[str, Any] = {
        "success": True,
        "difficulties_list": difficulties_list,
        "reasons": reasons,
        "correction": correction,
        "fallback": True,
    }
    if error:
        payload["fallback_reason"] = error
    return payload


def call_ai_api_with_retry(
    api_key: str,
    achieved: str,
    difficulties: str,
    model: str = DEFAULT_AI_MODEL,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> dict[str, Any] | None:
    """Вызов Qwen API с экспоненциальной задержкой при ошибках сети или лимитов."""
    try:
        from openai import APIConnectionError, APIError, OpenAI, RateLimitError
    except ImportError:
        logger.warning("OpenAI library not installed")
        return None

    client = OpenAI(
        api_key=api_key,
        base_url=DASHSCOPE_BASE_URL,
        timeout=30.0,
    )
    user_prompt = build_user_prompt(achieved, difficulties)
    resolved_model = (model or "").strip() or DEFAULT_AI_MODEL
    last_error: Exception | str | None = None

    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=resolved_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=500,
            )
            response_text = completion.choices[0].message.content
            parsed = parse_ai_json_response(response_text)
            if parsed is not None:
                return parsed
            logger.error("JSON decode error from AI response")
            return None

        except RateLimitError as e:
            last_error = e
            delay = base_delay * (2**attempt) * 2
            logger.warning("API rate limit (attempt %s): %s. Waiting %ss...", attempt + 1, e, delay)
            if attempt < max_retries - 1:
                time.sleep(delay)

        except (APIConnectionError, APIError) as e:
            last_error = e
            delay = base_delay * (2**attempt)
            logger.warning("API error (attempt %s): %s. Waiting %ss...", attempt + 1, e, delay)
            if attempt < max_retries - 1:
                time.sleep(delay)

        except Exception as e:
            last_error = e
            logger.error("Unexpected AI error (attempt %s): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(base_delay)

    logger.error("All %s AI API attempts failed. Last error: %s", max_retries, last_error)
    return None


def generate_goals_analysis_for_user(
    user: User,
    achieved: str,
    difficulties: str,
) -> dict[str, Any]:
    """Генерирует ИИ-анализ целей для учителя (или возвращает шаблонный fallback)."""
    api_key, ai_model = resolve_school_ai_credentials(user)
    if not api_key:
        return generate_fallback_analysis_dict(achieved, difficulties)

    result = call_ai_api_with_retry(api_key, achieved, difficulties, model=ai_model)
    if result:
        return {
            "success": True,
            "difficulties_list": result.get("difficulties_list", ""),
            "reasons": result.get("reasons", ""),
            "correction": result.get("correction", ""),
        }
    return generate_fallback_analysis_dict(achieved, difficulties)
