import sqlite3
import json
from config import DATA_DIR
import os

DB_PATH = os.path.join(DATA_DIR, 'settings.db')

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posts_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            affirmation TEXT NOT NULL,
            image_path TEXT,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Настройки по умолчанию
    default_settings = {
        'prompt': 'Создай короткую мотивирующую аффирмацию на русском языке (1-2 предложения). Аффирмация должна быть позитивной, вдохновляющей и в настоящем времени.',
        'model': 'tinyllama',
        'posts_per_day': '3',
        'image_prompt_template': 'Simple minimalist illustration for affirmation: {affirmation}'
    }
    
    for key, value in default_settings.items():
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    
    # Расписание по умолчанию
    default_times = ['09:00', '15:00', '21:00']
    cursor.execute('SELECT COUNT(*) FROM schedule')
    if cursor.fetchone()[0] == 0:
        for time in default_times:
            cursor.execute('INSERT INTO schedule (time) VALUES (?)', (time,))
    
    conn.commit()
    conn.close()

def get_setting(key):
    """Получить настройку"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_setting(key, value):
    """Установить настройку"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_schedule():
    """Получить расписание"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, time, active FROM schedule ORDER BY time')
    schedule = cursor.fetchall()
    conn.close()
    return schedule

def add_schedule_time(time):
    """Добавить время в расписание"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO schedule (time) VALUES (?)', (time,))
    conn.commit()
    conn.close()

def remove_schedule_time(schedule_id):
    """Удалить время из расписания"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM schedule WHERE id = ?', (schedule_id,))
    conn.commit()
    conn.close()

def toggle_schedule_time(schedule_id):
    """Включить/выключить время"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE schedule SET active = NOT active WHERE id = ?', (schedule_id,))
    conn.commit()
    conn.close()

def save_post_history(affirmation, image_path):
    """Сохранить историю поста"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO posts_history (affirmation, image_path) VALUES (?, ?)', 
                   (affirmation, image_path))
    conn.commit()
    conn.close()

def get_posts_history(limit=10):
    """Получить историю постов"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT affirmation, posted_at FROM posts_history ORDER BY posted_at DESC LIMIT ?', (limit,))
    history = cursor.fetchall()
    conn.close()
    return history