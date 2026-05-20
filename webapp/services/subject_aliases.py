"""Словарь соответствий названий предметов (казахский вариант → канон на русском)."""

from __future__ import annotations

from ..constants import DEFAULT_SUBJECT_ALIASES, _apply_subject_aliases, _base_normalize_subject_name
from ..extensions import db
from ..models import SubjectNameAlias


def get_school_aliases(school_id: int) -> dict[str, str]:
    """Алиасы школы поверх дефолтов; при пустой таблице засеивает стандартный словарь."""
    ensure_default_aliases(school_id)
    rows = SubjectNameAlias.query.filter_by(school_id=school_id).all()
    return {r.alias_name: r.canonical_name for r in rows}


def ensure_default_aliases(school_id: int) -> None:
    """Добавляет недостающие записи из DEFAULT_SUBJECT_ALIASES для школы."""
    existing = {
        r.alias_name
        for r in SubjectNameAlias.query.filter_by(school_id=school_id).all()
    }
    added = False
    for alias, canonical in DEFAULT_SUBJECT_ALIASES.items():
        if alias not in existing:
            db.session.add(
                SubjectNameAlias(
                    school_id=school_id,
                    alias_name=alias,
                    canonical_name=canonical,
                )
            )
            added = True
    if added:
        db.session.commit()


def restore_default_aliases(school_id: int) -> int:
    """Добавляет отсутствующие дефолтные пары; не удаляет пользовательские."""
    ensure_default_aliases(school_id)
    return len(DEFAULT_SUBJECT_ALIASES)


def normalize_subject_name(raw: str, school_id: int | None = None) -> str:
    """Нормализация с учётом словаря школы (или только дефолтов без school_id)."""
    name = _base_normalize_subject_name(raw)
    aliases = dict(DEFAULT_SUBJECT_ALIASES)
    if school_id is not None:
        aliases.update(get_school_aliases(school_id))
    return _apply_subject_aliases(name, aliases)
