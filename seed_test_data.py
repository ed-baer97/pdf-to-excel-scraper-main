"""
Скрипт для загрузки тестовых данных в базу.
Добавляет классы, предметы и оценки учеников.
"""
import sys
import json
sys.path.insert(0, '.')

from webapp import create_app
from webapp.extensions import db
from webapp.models import (
    User, School, Role, GradeReport, Class
)

app = create_app()

with app.app_context():
    db.create_all()

    # --- Проверяем что есть ---
    school = School.query.first()
    if not school:
        print("ОШИБКА: Школа не найдена. Сначала создайте школу через /setup")
        sys.exit(1)

    teachers = User.query.filter_by(role=Role.TEACHER.value, school_id=school.id).all()
    if not teachers:
        print("ОШИБКА: Учителя не найдены. Сначала создайте учителей через админ-панель")
        sys.exit(1)

    print(f"Школа: {school.name} (ID={school.id})")
    print(f"Учителя: {[(t.id, t.username, t.full_name) for t in teachers]}")

    # --- Создаём классы ---
    class_names = ["5А", "5Б", "7А", "7Б", "9А", "9Б", "11А"]
    created_classes = {}

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

    # --- Тестовые ученики ---
    students_7a = [
        "Алиев Алмас", "Бекова Дана", "Волков Данил",
        "Галиева Айгерим", "Досымов Арман", "Ермеков Тимур",
        "Жакупова Камила", "Исмаилов Рустам", "Касымова Динара",
        "Лебедев Максим", "Мухамедова Алия", "Нурланов Бауыржан",
        "Оспанова Мадина", "Петров Сергей", "Рахимова Аида",
        "Сатыбалдиев Ерлан", "Турсынбаева Жанна", "Усенов Даулет",
        "Федорова Елена", "Хамитова Асель"
    ]

    students_7b = [
        "Абдрахманов Нурбек", "Байжанова Сауле", "Григорьев Артем",
        "Джумабаева Карина", "Есенова Жанар", "Зайцев Дмитрий",
        "Ибрагимова Лейла", "Козлов Никита", "Муратова Гульнар",
        "Оразалиев Канат", "Пак Виктория", "Сагындыков Адиль",
        "Тулегенова Нургуль", "Уразов Бекзат", "Хасенова Фарида",
        "Шарипов Марат"
    ]

    students_9a = [
        "Ахметов Нуржан", "Борисова Анна", "Габдуллин Ильяс",
        "Давлетова Асем", "Егоров Владислав", "Жумабекова Айым",
        "Искаков Темирлан", "Калиева Сабина", "Литвинов Андрей",
        "Мусина Зарина", "Назарбаева Амина", "Омаров Санжар",
        "Попова Кристина", "Рустемов Данияр", "Султанова Малика",
        "Тасболатов Ержан", "Ульянова Дарья", "Файзуллин Ринат"
    ]

    students_5a = [
        "Аманов Бауыржан", "Белова Полина", "Власов Кирилл",
        "Гусева Диана", "Дюсенбаев Абылай", "Ефимова Софья",
        "Жангелдин Тамерлан", "Зубова Алиса", "Ильясов Амир",
        "Краснова Варвара", "Лукманов Ислам", "Минина Ева",
        "Нурпеисов Ален", "Орлова Милана", "Пашков Тимофей"
    ]

    # --- Генератор оценок ---
    import random
    random.seed(42)  # Фиксированный seed для воспроизводимости

    def generate_grades(student_names):
        """Генерирует реалистичные оценки для списка учеников"""
        students = []
        grades_count = {"5": 0, "4": 0, "3": 0, "2": 0}

        for name in student_names:
            # Реалистичное распределение: большинство 4-5, немного 3
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
            "total_students": total
        }

    def generate_analytics():
        """Генерирует данные аналитики СОР/СОЧ"""
        sor_list = []
        for i in range(1, 4):
            sor_list.append({
                "name": f"СОр {i}",
                "count_5": random.randint(3, 8),
                "count_4": random.randint(4, 10),
                "count_3": random.randint(2, 6),
                "count_2": random.randint(0, 2)
            })

        return {
            "sor": sor_list,
            "soch": {
                "count_5": random.randint(4, 9),
                "count_4": random.randint(5, 10),
                "count_3": random.randint(2, 5),
                "count_2": random.randint(0, 2)
            }
        }

    # --- Распределяем предметы по учителям и создаём отчёты ---
    # Назначаем предметы и классы
    assignments = [
        # (предмет, класс, ученики)
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

    report_count = 0
    for idx, (subject_name, class_name, student_list) in enumerate(assignments):
        # Берём учителя по кругу
        teacher = teachers[idx % len(teachers)]

        # Создаём отчёт для 2-й четверти
        existing = GradeReport.query.filter_by(
            teacher_id=teacher.id,
            school_id=school.id,
            class_name=class_name,
            subject_name=subject_name,
            period_type="quarter",
            period_number=2
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
                analytics_json=json.dumps(analytics_data, ensure_ascii=False)
            )
            db.session.add(report)
            report_count += 1
            print(f"  Отчёт: {class_name} - {subject_name} (учитель: {teacher.username})")
        else:
            print(f"  Уже есть: {class_name} - {subject_name}")

    # Назначаем классных руководителей (первым учителям)
    if len(teachers) >= 1:
        cls_7a = created_classes.get("7А")
        if cls_7a and not cls_7a.class_teacher_id:
            cls_7a.class_teacher_id = teachers[0].id
            print(f"  Классный руководитель 7А: {teachers[0].username}")

    if len(teachers) >= 2:
        cls_9a = created_classes.get("9А")
        if cls_9a and not cls_9a.class_teacher_id:
            cls_9a.class_teacher_id = teachers[1 % len(teachers)].id
            print(f"  Классный руководитель 9А: {teachers[1 % len(teachers)].username}")

    db.session.commit()

    print(f"\n{'='*50}")
    print(f"Готово!")
    print(f"  Классов: {len(created_classes)}")
    print(f"  Новых отчётов: {report_count}")
    print(f"{'='*50}")
    print(f"\nТеперь откройте http://localhost:5000 и войдите как админ.")
    print(f"Перейдите в /admin/grades чтобы увидеть оценки.")
