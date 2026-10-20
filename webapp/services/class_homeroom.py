"""Классный руководитель по учебным годам и автоперевод параллели.

В архиве прошлого года руководитель остаётся у своего класса (5Е).
В следующем учебном году тот же человек автоматически становится
классным руководителем следующей параллели (6Е). 11 класс выпускной:
дальше перевод не идёт.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extensions import db
from ..models import Class, ClassTeacherYear, GradeReport, User
from .academic_year import current_academic_year

MAX_CLASS_GRADE = 11
_CLASS_NAME_RE = re.compile(r"^(\d+)(.*)$", re.DOTALL)


def shift_class_name(name: str, delta: int) -> str | None:
    """Сдвинуть параллель: «5Е» + 1 → «6Е». None, если параллель вне 1..11."""
    raw = str(name or "").strip()
    match = _CLASS_NAME_RE.match(raw)
    if not match:
        return None
    grade = int(match.group(1)) + int(delta)
    if grade < 1 or grade > MAX_CLASS_GRADE:
        return None
    return f"{grade}{match.group(2)}"


@dataclass
class HomeroomIndex:
    """Снимок назначений школы: явные строки и год, с которого они начались."""

    snapshot_year: int
    by_name: dict[str, Class] = field(default_factory=dict)
    explicit: dict[tuple[int, int], int | None] = field(default_factory=dict)

    def teacher_id(self, class_name: str, year: int, seen: set | None = None) -> int | None:
        """Id классного руководителя класса в учебном году."""
        folded = str(class_name or "").strip().casefold()
        if not folded:
            return None
        seen = set() if seen is None else seen
        marker = (folded, year)
        if marker in seen:
            return None
        seen.add(marker)

        cls = self.by_name.get(folded)
        if cls is not None and (cls.id, year) in self.explicit:
            return self.explicit[(cls.id, year)]

        if year < self.snapshot_year:
            return self.teacher_id(class_name, self.snapshot_year, seen)
        if year == self.snapshot_year:
            return None

        previous = shift_class_name(class_name, -1)
        if previous is None:
            return None
        return self.teacher_id(previous, year - 1, seen)


def initial_snapshot_year(school_id: int) -> int:
    """Куда записать уже существующие назначения, у которых ещё нет года.

    Если в школе есть оценки прошлых лет, текущая колонка class_teacher_id
    считается назначением прошлого учебного года. Иначе — текущего.
    """
    current = current_academic_year()
    past = (
        db.session.query(GradeReport.id)
        .filter(
            GradeReport.school_id == school_id,
            GradeReport.academic_year < current,
        )
        .limit(1)
        .first()
    )
    if past is not None:
        return current - 1
    return current


def ensure_legacy_anchors(school_id: int) -> None:
    """Один раз зафиксировать текущие class_teacher_id как назначения года-снимка."""
    linked = (
        db.session.query(ClassTeacherYear.id)
        .join(Class, Class.id == ClassTeacherYear.class_id)
        .filter(Class.school_id == school_id)
        .limit(1)
        .first()
    )
    if linked is not None:
        return

    year = initial_snapshot_year(school_id)
    classes = Class.query.filter_by(school_id=school_id).all()
    for cls in classes:
        if not cls.class_teacher_id:
            continue
        db.session.add(
            ClassTeacherYear(
                class_id=cls.id,
                academic_year=year,
                teacher_id=cls.class_teacher_id,
            )
        )
    db.session.flush()


def load_homeroom_index(school_id: int) -> HomeroomIndex:
    """Явные назначения школы. Год снимка — самый ранний сохранённый год."""
    classes = Class.query.filter_by(school_id=school_id).all()
    class_ids = [cls.id for cls in classes]
    rows = (
        ClassTeacherYear.query.filter(ClassTeacherYear.class_id.in_(class_ids)).all()
        if class_ids
        else []
    )
    explicit = {(row.class_id, row.academic_year): row.teacher_id for row in rows}
    if explicit:
        snapshot = min(year for _, year in explicit)
    else:
        snapshot = initial_snapshot_year(school_id)
    by_name: dict[str, Class] = {}
    for cls in classes:
        by_name.setdefault(cls.name.casefold(), cls)
    return HomeroomIndex(snapshot_year=snapshot, by_name=by_name, explicit=explicit)


def ensure_promoted_classes(school_id: int, year: int, index: HomeroomIndex) -> bool:
    """Создать класс следующей параллели, если в прошлом году у этой параллели был классный."""
    if year <= index.snapshot_year:
        return False
    created = False
    known = set(index.by_name)
    for cls in list(index.by_name.values()):
        nxt = shift_class_name(cls.name, 1)
        if not nxt or nxt.casefold() in known:
            continue
        if not index.teacher_id(cls.name, year - 1):
            continue
        db.session.add(Class(school_id=school_id, name=nxt))
        known.add(nxt.casefold())
        created = True
    if created:
        db.session.flush()
    return created


def sync_current_cache(school_id: int, index: HomeroomIndex) -> bool:
    """Колонка classes.class_teacher_id отражает текущий учебный год."""
    year = current_academic_year()
    changed = False
    for cls in Class.query.filter_by(school_id=school_id).all():
        teacher_id = index.teacher_id(cls.name, year)
        if cls.class_teacher_id != teacher_id:
            cls.class_teacher_id = teacher_id
            changed = True
    return changed


def prepare_class_teachers(school_id: int, year: int) -> HomeroomIndex:
    """Зафиксировать архив, завести следующую параллель и обновить кэш текущего года."""
    ensure_legacy_anchors(school_id)
    index = load_homeroom_index(school_id)
    if ensure_promoted_classes(school_id, year, index):
        index = load_homeroom_index(school_id)
    current = current_academic_year()
    if year != current and current > index.snapshot_year:
        if ensure_promoted_classes(school_id, current, index):
            index = load_homeroom_index(school_id)
    sync_current_cache(school_id, index)
    db.session.commit()
    return index


def class_teacher_map(school_id: int, year: int, index: HomeroomIndex | None = None) -> dict[int, User]:
    """class_id → пользователь-классный в выбранном году."""
    if index is None:
        index = prepare_class_teachers(school_id, year)
    classes = Class.query.filter_by(school_id=school_id).all()
    ids: dict[int, int] = {}
    for cls in classes:
        teacher_id = index.teacher_id(cls.name, year)
        if teacher_id:
            ids[cls.id] = teacher_id
    if not ids:
        return {}
    users = User.query.filter(User.id.in_(set(ids.values()))).all()
    by_user = {user.id: user for user in users}
    return {class_id: by_user[teacher_id] for class_id, teacher_id in ids.items() if teacher_id in by_user}


def class_teacher_user(school_id: int, class_name: str, year: int) -> User | None:
    """Классный руководитель класса в учебном году."""
    index = prepare_class_teachers(school_id, year)
    teacher_id = index.teacher_id(class_name, year)
    if not teacher_id:
        return None
    return db.session.get(User, teacher_id)


def managed_classes(school_id: int, teacher_id: int, year: int) -> list[Class]:
    """Классы, где учитель — классный руководитель в этом учебном году."""
    index = prepare_class_teachers(school_id, year)
    classes = Class.query.filter_by(school_id=school_id).all()
    owned = [
        cls
        for cls in classes
        if index.teacher_id(cls.name, year) == teacher_id
    ]
    owned.sort(key=lambda cls: cls.name)
    return owned


def assign_class_teacher(cls: Class, teacher_id: int | None, year: int) -> None:
    """Явное назначение на учебный год. None снимает классного и блокирует автоперевод."""
    ensure_legacy_anchors(cls.school_id)
    row = ClassTeacherYear.query.filter_by(class_id=cls.id, academic_year=year).one_or_none()
    if row is None:
        db.session.add(
            ClassTeacherYear(
                class_id=cls.id,
                academic_year=year,
                teacher_id=teacher_id,
            )
        )
    else:
        row.teacher_id = teacher_id
    if year == current_academic_year():
        cls.class_teacher_id = teacher_id
    db.session.flush()


def clear_homeroom_teacher(teacher_id: int, school_id: int) -> None:
    """Снять учителя со всех классов школы, включая архивные годы."""
    class_ids = [
        class_id
        for (class_id,) in Class.query.filter_by(school_id=school_id).with_entities(Class.id).all()
    ]
    if class_ids:
        ClassTeacherYear.query.filter(
            ClassTeacherYear.class_id.in_(class_ids),
            ClassTeacherYear.teacher_id == teacher_id,
        ).delete(synchronize_session=False)
    Class.query.filter_by(
        school_id=school_id,
        class_teacher_id=teacher_id,
    ).update({"class_teacher_id": None}, synchronize_session=False)
