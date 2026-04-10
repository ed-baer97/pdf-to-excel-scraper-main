"""
Тестовые данные для школы «Test»: учителя, классы, предметы, связи и оценки (GradeReport).
Администратор школы не создаётся — должен уже существовать.

Запуск из корня проекта:
  python seed_test_data.py
"""
from __future__ import annotations

import json
import random
import sys

sys.path.insert(0, ".")

from sqlalchemy import func

from webapp import create_app
from webapp.extensions import db
from webapp.models import (
    Class,
    GradeReport,
    Role,
    School,
    Subject,
    TeacherClass,
    TeacherSubject,
    User,
)
from webapp.security import encrypt_password

SCHOOL_NAME = "Test"

# Два демо-учителя (идемпотентно: при повторном запуске не дублируются)
TEACHER_SEEDS = [
    {"username": "test_teacher_math", "full_name": "Иванов Иван Иванович"},
    {"username": "test_teacher_lang", "full_name": "Сидорова Мария Петровна"},
]
TEACHER_PASSWORD = "TestDemo123!"

app = create_app()

with app.app_context():
    db.create_all()

    school = School.query.filter_by(name=SCHOOL_NAME).first()
    if not school:
        print(f"ОШИБКА: школа «{SCHOOL_NAME}» не найдена. Создайте её в супер-админке.")
        sys.exit(1)

    enc_key = app.config.get("PASSWORD_ENC_KEY", "")

    max_seq = (
        db.session.query(func.max(User.fs_teacher_seq))
        .filter(User.school_id == school.id, User.role == Role.TEACHER.value)
        .scalar()
    )
    next_seq = int(max_seq or 0) + 1

    teachers: list[User] = []
    for spec in TEACHER_SEEDS:
        existing = User.query.filter_by(username=spec["username"]).first()
        if existing:
            if existing.school_id != school.id:
                print(
                    f"ОШИБКА: логин {spec['username']} уже занят другой школой."
                )
                sys.exit(1)
            if existing.role != Role.TEACHER.value:
                print(f"ОШИБКА: {spec['username']} не учитель.")
                sys.exit(1)
            teachers.append(existing)
            print(f"  Учитель уже есть: {spec['username']}")
            continue
        u = User(
            username=spec["username"],
            full_name=spec["full_name"],
            role=Role.TEACHER.value,
            school_id=school.id,
            is_active=True,
            fs_teacher_seq=next_seq,
        )
        next_seq += 1
        u.set_password(TEACHER_PASSWORD)
        u.password_enc = encrypt_password(TEACHER_PASSWORD, enc_key)
        db.session.add(u)
        db.session.flush()
        teachers.append(u)
        print(f"  Учитель создан: {spec['username']} (пароль: {TEACHER_PASSWORD})")

    db.session.commit()
    # Стабильный порядок для round-robin отчётов
    teachers = (
        User.query.filter(User.id.in_([t.id for t in teachers]))
        .order_by(User.username)
        .all()
    )

    print(f"\nШкола: {school.name} (id={school.id})")
    print(f"Учителя для демо-отчётов: {[t.username for t in teachers]}")

    # --- Классы ---
    class_names = ["5А", "5Б", "7А", "7Б", "9А", "9Б", "11А"]
    created_classes: dict[str, Class] = {}

    for name in class_names:
        existing = Class.query.filter_by(school_id=school.id, name=name).first()
        if not existing:
            c = Class(school_id=school.id, name=name)
            db.session.add(c)
            db.session.flush()
            created_classes[name] = c
            print(f"  Класс создан: {name}")
        else:
            created_classes[name] = existing
            print(f"  Класс уже есть: {name}")

    db.session.commit()

    students_7a = [
        "Алиев Алмас", "Бекова Дана", "Волков Данил",
        "Галиева Айгерим", "Досымов Арман", "Ермеков Тимур",
        "Жакупова Камила", "Исмаилов Рустам", "Касымова Динара",
        "Лебедев Максим", "Мухамедова Алия", "Нурланов Бауыржан",
        "Оспанова Мадина", "Петров Сергей", "Рахимова Аида",
        "Сатыбалдиев Ерлан", "Турсынбаева Жанна", "Усенов Даулет",
        "Федорова Елена", "Хамитова Асель",
    ]

    students_7b = [
        "Абдрахманов Нурбек", "Байжанова Сауле", "Григорьев Артем",
        "Джумабаева Карина", "Есенова Жанар", "Зайцев Дмитрий",
        "Ибрагимова Лейла", "Козлов Никита", "Муратова Гульнар",
        "Оразалиев Канат", "Пак Виктория", "Сагындыков Адиль",
        "Тулегенова Нургуль", "Уразов Бекзат", "Хасенова Фарида",
        "Шарипов Марат",
    ]

    students_9a = [
        "Ахметов Нуржан", "Борисова Анна", "Габдуллин Ильяс",
        "Давлетова Асем", "Егоров Владислав", "Жумабекова Айым",
        "Искаков Темирлан", "Калиева Сабина", "Литвинов Андрей",
        "Мусина Зарина", "Назарбаева Амина", "Омаров Санжар",
        "Попова Кристина", "Рустемов Данияр", "Султанова Малика",
        "Тасболатов Ержан", "Ульянова Дарья", "Файзуллин Ринат",
    ]

    students_5a = [
        "Аманов Бауыржан", "Белова Полина", "Власов Кирилл",
        "Гусева Диана", "Дюсенбаев Абылай", "Ефимова Софья",
        "Жангелдин Тамерлан", "Зубова Алиса", "Ильясов Амир",
        "Краснова Варвара", "Лукманов Ислам", "Минина Ева",
        "Нурпеисов Ален", "Орлова Милана", "Пашков Тимофей",
    ]

    random.seed(42)

    def generate_grades(student_names: list[str]) -> dict:
        students = []
        grades_count = {"5": 0, "4": 0, "3": 0, "2": 0}

        for name in student_names:
            r = random.random()
            if r < 0.25:
                grade = 5
                percent = round(random.uniform(85, 100), 1)
            elif r < 0.65:
                grade = 4
                percent = round(random.uniform(65, 84), 1)
            elif r < 0.90:
                grade = 3
                percent = round(random.uniform(40, 64), 1)
            else:
                grade = 2
                percent = round(random.uniform(15, 39), 1)

            students.append({"name": name, "percent": percent, "grade": grade})
            grades_count[str(grade)] += 1

        total = len(students)
        quality = grades_count["5"] + grades_count["4"]
        success = quality + grades_count["3"]

        return {
            "students": students,
            "quality_percent": round(quality / total * 100, 1) if total else 0,
            "success_percent": round(success / total * 100, 1) if total else 0,
            "total_students": total,
        }

    def generate_analytics() -> dict:
        sor_list = []
        for i in range(1, 4):
            sor_list.append({
                "name": f"СОр {i}",
                "count_5": random.randint(3, 8),
                "count_4": random.randint(4, 10),
                "count_3": random.randint(2, 6),
                "count_2": random.randint(0, 2),
            })

        return {
            "sor": sor_list,
            "soch": {
                "count_5": random.randint(4, 9),
                "count_4": random.randint(5, 10),
                "count_3": random.randint(2, 5),
                "count_2": random.randint(0, 2),
            },
        }

    assignments: list[tuple[str, str, list[str]]] = [
        ("Математика", "7А", students_7a),
        ("Физика", "7А", students_7a),
        ("Русский язык", "7А", students_7a),
        ("Казахский язык", "7А", students_7a),
        ("Английский язык", "7А", students_7a),
        ("Математика", "7Б", students_7b),
        ("Физика", "7Б", students_7b),
        ("Русский язык", "7Б", students_7b),
        ("Математика", "9А", students_9a),
        ("Физика", "9А", students_9a),
        ("Химия", "9А", students_9a),
        ("Биология", "9А", students_9a),
        ("История Казахстана", "9А", students_9a),
        ("Информатика", "9А", students_9a),
        ("Математика", "5А", students_5a),
        ("Русский язык", "5А", students_5a),
        ("Казахский язык", "5А", students_5a),
        ("Английский язык", "5А", students_5a),
    ]

    if len(teachers) < 1:
        print("ОШИБКА: нет учителей для привязки.")
        sys.exit(1)

    def get_or_create_subject(name: str) -> Subject:
        subj = Subject.query.filter_by(school_id=school.id, name=name).first()
        if not subj:
            subj = Subject(school_id=school.id, name=name)
            db.session.add(subj)
            db.session.flush()
            print(f"  Предмет создан: {name}")
        return subj

    report_count = 0
    links_count = 0

    for idx, (subject_name, class_name, student_list) in enumerate(assignments):
        teacher = teachers[idx % len(teachers)]
        subj = get_or_create_subject(subject_name)
        cls_obj = created_classes.get(class_name)
        if not cls_obj:
            print(f"  Пропуск: класс {class_name} не найден среди созданных")
            continue

        ts = TeacherSubject.query.filter_by(
            teacher_id=teacher.id, subject_id=subj.id
        ).first()
        if not ts:
            ts = TeacherSubject(teacher_id=teacher.id, subject_id=subj.id)
            db.session.add(ts)
            db.session.flush()
            links_count += 1

        tc = TeacherClass.query.filter_by(
            teacher_subject_id=ts.id, class_id=cls_obj.id
        ).first()
        if not tc:
            tc = TeacherClass(
                teacher_subject_id=ts.id, class_id=cls_obj.id, subgroup=None
            )
            db.session.add(tc)
            links_count += 1

        existing = GradeReport.query.filter_by(
            teacher_id=teacher.id,
            school_id=school.id,
            class_name=class_name,
            subject_name=subject_name,
            period_type="quarter",
            period_number=2,
        ).first()

        if not existing:
            grades_data = generate_grades(student_list)
            analytics_data = generate_analytics()
            report = GradeReport(
                teacher_id=teacher.id,
                school_id=school.id,
                class_name=class_name,
                subject_name=subject_name,
                period_type="quarter",
                period_number=2,
                grades_json=json.dumps(grades_data, ensure_ascii=False),
                analytics_json=json.dumps(analytics_data, ensure_ascii=False),
            )
            db.session.add(report)
            report_count += 1
            print(
                f"  Отчёт: {class_name} — {subject_name} (учитель: {teacher.username})"
            )
        else:
            print(f"  Отчёт уже есть: {class_name} — {subject_name}")

    if len(teachers) >= 1:
        cls_7a = created_classes.get("7А")
        if cls_7a and not cls_7a.class_teacher_id:
            cls_7a.class_teacher_id = teachers[0].id
            print(f"  Классный руководитель 7А: {teachers[0].username}")

    if len(teachers) >= 2:
        cls_9a = created_classes.get("9А")
        if cls_9a and not cls_9a.class_teacher_id:
            cls_9a.class_teacher_id = teachers[1].id
            print(f"  Классный руководитель 9А: {teachers[1].username}")

    db.session.commit()

    print(f"\n{'=' * 50}")
    print("Готово.")
    print(f"  Классов в наборе: {len(created_classes)}")
    print(f"  Новых отчётов с оценками: {report_count}")
    print(f"  Новых связей учитель-предмет-класс (прибл.): {links_count}")
    print(f"{'=' * 50}")
    print("\nЛогины демо-учителей и пароль (одинаковый для новых):")
    for spec in TEACHER_SEEDS:
        print(f"  {spec['username']}: {TEACHER_PASSWORD} (если учитель только что создан)")
    print("\nАдмин-панель: /admin/management — классы, предметы, оценки.")
