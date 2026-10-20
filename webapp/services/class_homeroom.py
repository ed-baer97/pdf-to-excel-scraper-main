"""Классный руководитель по учебным годам и автоперевод параллели.

В архиве прошлого года руководитель остаётся у своего класса.
В новом году он переходит на следующую параллель: 2Е→3Е, 5Е→6Е, 10Б→11Б.
Исключения: с 4 и 11 классов руководитель дальше не переходит и на следующий
год остаётся без класса. 1 и 5 классы автопереводом не заполняются —
их назначают вручную. Архив при этом не меняется.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extensions import db
from ..models import Class, ClassTeacherYear, GradeReport, User
from .academic_year import current_academic_year

MAX_CLASS_GRADE = 11
# С этих параллелей руководитель на следующий год не переходит.
TERMINAL_GRADES = frozenset({4, 11})
# Эти параллели не заполняются переводом с прошлого класса.
MANUAL_ENTRY_GRADES = frozenset({1, 5})
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
        # 4→5 и 11→дальше не выводятся. 1 и 5 назначают вручную.
        if previous is None or homeroom_next_class(previous) is None:
            return None
        if homeroom_next_class(previous).casefold() != folded:
            return None
        candidate = self.teacher_id(previous, year - 1, seen)
        if candidate is None:
            return None
        # Уже стоит на параллели этого года — не переносить его ещё на класс выше.
        placed = self.explicit_class_ids(candidate, year)
        if placed:
            current_cls = self.by_name.get(folded)
            if current_cls is None or current_cls.id not in placed:
                return None
        return candidate

    def explicit_class_ids(self, teacher_id: int, year: int) -> set[int]:
        """Классы, куда учитель явно назначен в этом учебном году."""
        return {
            class_id
            for (class_id, row_year), row_teacher in self.explicit.items()
            if row_year == year and row_teacher == teacher_id
        }


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


def _class_grade(name: str) -> int | None:
    match = _CLASS_NAME_RE.match(str(name or "").strip())
    return int(match.group(1)) if match else None


def homeroom_next_class(name: str) -> str | None:
    """Куда переходит классный. None для 4 и 11 и для входа в 1 и 5."""
    if _class_grade(name) in TERMINAL_GRADES:
        return None
    nxt = shift_class_name(name, 1)
    if nxt is None or _class_grade(nxt) in MANUAL_ENTRY_GRADES:
        return None
    return nxt


def _archive_names(school_id: int, year: int) -> set[str]:
    rows = (
        db.session.query(GradeReport.class_name)
        .filter(
            GradeReport.school_id == school_id,
            GradeReport.academic_year == year,
        )
        .distinct()
        .all()
    )
    return {str(name).casefold() for (name,) in rows if name}


def _remember_assignment(
    pending: dict[tuple[int, int], int | None],
    class_id: int,
    year: int,
    teacher_id: int | None,
) -> None:
    pending.setdefault((class_id, year), teacher_id)


def ensure_legacy_anchors(school_id: int) -> None:
    """Зафиксировать уже введённых классных, не сдвигая их второй раз.

    Если в программе учитель уже стоит и на 5Д, и на 6Д (или 5Д освободили,
    а его поставили на 6Д), прошлый год остаётся 5Д, текущий — 6Д.
    В 7Д он при этом не попадает.
    """
    linked = (
        db.session.query(ClassTeacherYear.id)
        .join(Class, Class.id == ClassTeacherYear.class_id)
        .filter(Class.school_id == school_id)
        .limit(1)
        .first()
    )
    if linked is not None:
        return

    current = current_academic_year()
    snapshot = initial_snapshot_year(school_id)
    classes = Class.query.filter_by(school_id=school_id).all()
    by_name = {cls.name.casefold(): cls for cls in classes}
    pending: dict[tuple[int, int], int | None] = {}

    if snapshot == current:
        for cls in classes:
            if cls.class_teacher_id:
                _remember_assignment(pending, cls.id, current, cls.class_teacher_id)
        _flush_assignments(pending)
        return

    archive_names = _archive_names(school_id, snapshot)
    by_teacher: dict[int, list[Class]] = {}
    for cls in classes:
        if cls.class_teacher_id:
            by_teacher.setdefault(cls.class_teacher_id, []).append(cls)

    for teacher_id, owned in by_teacher.items():
        owned_names = {cls.name.casefold(): cls for cls in owned}
        lowest = min(owned, key=lambda cls: (_class_grade(cls.name) or 999, cls.name.casefold()))
        one_up_name = shift_class_name(lowest.name, 1)
        one_up = owned_names.get(one_up_name.casefold()) if one_up_name else None
        if one_up is not None:
            # Уже переведён на следующую параллель: 5Д остаётся в архиве, 6Д — в этом году.
            _remember_assignment(pending, lowest.id, snapshot, teacher_id)
            _remember_assignment(pending, one_up.id, current, teacher_id)
            for cls in owned:
                if cls.id not in (lowest.id, one_up.id):
                    _remember_assignment(pending, cls.id, snapshot, teacher_id)
            continue

        if len(owned) == 1:
            cls = owned[0]
            lower_name = shift_class_name(cls.name, -1)
            lower = by_name.get(lower_name.casefold()) if lower_name else None
            # 5Д освободили и этого человека уже поставили на 6Д.
            vacated = lower is not None and not lower.class_teacher_id
            # Класс переименовали: в архиве есть 5Д, а строки «6Д» в прошлом году не было.
            renamed = (
                lower is None
                and lower_name is not None
                and lower_name.casefold() in archive_names
                and cls.name.casefold() not in archive_names
            )
            if vacated or renamed:
                if lower is None and lower_name is not None:
                    lower = Class(school_id=school_id, name=lower_name)
                    db.session.add(lower)
                    db.session.flush()
                    by_name[lower.name.casefold()] = lower
                if lower is not None:
                    _remember_assignment(pending, lower.id, snapshot, teacher_id)
                    _remember_assignment(pending, cls.id, current, teacher_id)
                    continue

        for cls in owned:
            _remember_assignment(pending, cls.id, snapshot, teacher_id)

    _flush_assignments(pending)


def _flush_assignments(pending: dict[tuple[int, int], int | None]) -> None:
    for (class_id, year), teacher_id in pending.items():
        db.session.add(
            ClassTeacherYear(
                class_id=class_id,
                academic_year=year,
                teacher_id=teacher_id,
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
        nxt = homeroom_next_class(cls.name)
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
