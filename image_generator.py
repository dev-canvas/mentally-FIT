from PIL import Image, ImageDraw, ImageFont
import textwrap
import os
from config import IMAGES_DIR
import hashlib

def create_simple_image(affirmation):
    """Создание простой картинки с аффирмацией"""
    
    # Размеры изображения
    width, height = 800, 600
    
    # Пастельные цвета для фона
    colors = [
        (255, 239, 213),  # персиковый
        (230, 230, 250),  # лавандовый
        (240, 248, 255),  # голубой
        (255, 250, 240),  # кремовый
        (245, 255, 250),  # мятный
    ]
    
    # Выбираем цвет на основе хеша аффирмации для консистентности
    color_index = int(hashlib.md5(affirmation.encode()).hexdigest(), 16) % len(colors)
    bg_color = colors[color_index]
    
    # Создаем изображение
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Пробуем загрузить шрифт, иначе используем дефолтный
    try:
        font_size = 40
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
            "C:\\Windows\\Fonts\\Arial.ttf",  # Windows
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
        ]
        font = None
        for path in font_paths:
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except:
                continue
        if font is None:
            font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
    
    # Разбиваем текст на строки
    margin = 50
    max_width = width - 2 * margin
    
    # Простая функция для разбивки текста
    words = affirmation.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(' '.join(current_line))
    
    # Центрируем текст вертикально
    line_height = 50
    total_height = len(lines) * line_height
    start_y = (height - total_height) // 2
    
    # Рисуем текст
    text_color = (80, 80, 80)
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        y = start_y + i * line_height
        draw.text((x, y), line, fill=text_color, font=font)
    
    # Сохраняем изображение
    filename = f"affirmation_{hashlib.md5(affirmation.encode()).hexdigest()[:8]}.png"
    filepath = os.path.join(IMAGES_DIR, filename)
    img.save(filepath)
    
    return filepath