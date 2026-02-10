"""
AI Text Generator - генерация текстов анализа через Qwen API

Портировано из webapp/views/teacher.py с retry логикой.
"""
import json
import time
from typing import Dict, Optional


class AITextGenerator:
    """Генератор текстов через Qwen API"""
    
    SYSTEM_PROMPT = """Ты помощник учителя в Казахстане. Генерируй анализ суммативного оценивания (15-30 слов на поле).

СТРОГО РАЗЛИЧАЙ три поля:

"difficulties_list" = ЧТО НЕ ПОЛУЧИЛОСЬ (какие темы/задания вызвали трудности)
Пример: "Учащиеся допускали ошибки при решении уравнений с дробями и построении графиков линейных функций."

"reasons" = ПОЧЕМУ НЕ ПОЛУЧИЛОСЬ (причины затруднений)
Пример: "Слабо усвоены правила работы с дробями, недостаточно практики в построении координатных систем."

"correction" = ЧТО ДЕЛАТЬ (план коррекционной работы)
Пример: "Провести повторение темы 'Дроби', выполнить тренировочные упражнения по построению графиков."

JSON формат: {"difficulties_list": "...", "reasons": "...", "correction": "..."}"""
    
    DEFAULT_MODEL = "qwen-flash-character"

    def __init__(self, api_key: str, model: Optional[str] = None):
        """
        Инициализация генератора
        
        Args:
            api_key: API ключ Qwen/DashScope
            model: Модель AI (выбирает супер-админ; по умолчанию qwen-flash-character)
        """
        self.api_key = api_key
        self.model = (model or "").strip() or self.DEFAULT_MODEL
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Инициализация OpenAI клиента"""
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                timeout=30.0
            )
        except ImportError as e:
            raise ImportError(
                "Библиотека openai не установлена. "
                "Установите: pip install openai>=1.0.0"
            )
    
    def generate_analysis(
        self,
        achieved: str,
        difficulties: str,
        max_retries: int = 3,
        base_delay: float = 1.0
    ) -> Dict:
        """
        Генерация анализа с retry логикой
        
        Args:
            achieved: Достигнутые цели
            difficulties: Цели с затруднениями
            max_retries: Максимум попыток
            base_delay: Базовая задержка между попытками (секунды)
        
        Returns:
            dict: {
                "success": bool,
                "difficulties_list": str,
                "reasons": str,
                "correction": str,
                "error": str (если неуспешно)
            }
        """
        if not self.client:
            return {
                "success": False,
                "error": "AI клиент не инициализирован"
            }
        
        if not difficulties.strip():
            return {
                "success": False,
                "error": "Поле 'Цели с затруднениями' не может быть пустым"
            }
        
        user_prompt = f"""Цели обучения:

Достигнутые: {achieved or 'Не указаны'}

С затруднениями: {difficulties}

Заполни JSON:
- difficulties_list: перечисли ЧТО не получилось
- reasons: объясни ПОЧЕМУ не получилось  
- correction: напиши ЧТО ДЕЛАТЬ для исправления"""
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                from openai import APIError, APIConnectionError, RateLimitError
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7,
                    max_tokens=500,
                )
                
                content = response.choices[0].message.content
                result = json.loads(content)
                
                return {
                    "success": True,
                    "difficulties_list": result.get("difficulties_list", ""),
                    "reasons": result.get("reasons", ""),
                    "correction": result.get("correction", ""),
                }
            
            except RateLimitError as e:
                last_error = f"Rate limit: {str(e)}"
                delay = base_delay * (2 ** attempt) * 2
                if attempt < max_retries - 1:
                    time.sleep(delay)
            
            except APIConnectionError as e:
                last_error = f"Connection error: {str(e)}"
                delay = base_delay * (2 ** attempt)
                if attempt < max_retries - 1:
                    time.sleep(delay)
            
            except APIError as e:
                last_error = f"API error: {str(e)}"
                delay = base_delay * (2 ** attempt)
                if attempt < max_retries - 1:
                    time.sleep(delay)
            
            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {str(e)}"
                # Не retry на ошибках парсинга
                break
            
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                if attempt < max_retries - 1:
                    time.sleep(base_delay)
        
        # Все попытки неуспешны - возвращаем fallback
        return self._generate_fallback(achieved, difficulties, last_error)
    
    def _generate_fallback(
        self,
        achieved: str,
        difficulties: str,
        error: Optional[str] = None
    ) -> Dict:
        """Fallback генерация на основе шаблонов"""
        # Извлекаем ключевые моменты из затруднений
        diff_lines = [l.strip() for l in difficulties.split('\n') if l.strip()][:3]
        diff_summary = '; '.join([
            l.lstrip('0123456789.-* ')
            for l in diff_lines
        ]).lower()
        
        difficulties_list = ""
        if diff_summary:
            difficulties_list = (
                f"Обучающиеся испытывали затруднения при выполнении "
                f"заданий по темам: {diff_summary}."
            )
        
        reasons = (
            "Недостаточно сформированы навыки применения теоретических "
            "знаний на практике. Требуется дополнительная работа над "
            "закреплением материала."
        )
        
        correction = (
            "Провести индивидуальные консультации для устранения "
            "пробелов в знаниях. Повторить теоретический материал и "
            "выполнить практические упражнения."
        )
        
        return {
            "success": True,
            "difficulties_list": difficulties_list,
            "reasons": reasons,
            "correction": correction,
            "fallback": True,
            "fallback_reason": error
        }
