"""
Migration script: Add ai_api_key column to schools table

Запуск: python add_ai_api_key_column.py
"""
import sys
from pathlib import Path

# Add webapp to path
sys.path.insert(0, str(Path(__file__).parent))

from webapp import create_app, db

def add_ai_api_key_column():
    """Добавить колонку ai_api_key в таблицу schools"""
    app = create_app()
    
    with app.app_context():
        # Проверяем, существует ли уже колонка
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('schools')]
        
        if 'ai_api_key' in columns:
            print("✓ Колонка 'ai_api_key' уже существует в таблице schools")
            return
        
        # Добавляем колонку
        print("Добавление колонки 'ai_api_key' в таблицу schools...")
        
        with db.engine.connect() as conn:
            conn.execute(db.text(
                "ALTER TABLE schools ADD COLUMN ai_api_key VARCHAR(512)"
            ))
            conn.commit()
        
        print("✓ Колонка 'ai_api_key' успешно добавлена!")
        print("\nТеперь суперадмин может добавлять AI API ключи для каждой школы.")

if __name__ == "__main__":
    add_ai_api_key_column()
