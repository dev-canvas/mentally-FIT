import os
import sys
import logging
import random
import asyncio
import aiosqlite
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    FSInputFile,
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from PIL import Image, ImageDraw, ImageFont


# ========== Конфигурация ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHANNEL_ID = os.getenv("CHANNEL_ID")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "bot.db"
IMAGES_DIR = BASE_DIR / "images"
IMAGES_DIR.mkdir(exist_ok=True)

# ========== Логирование ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ========== Инициализация ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ========== Данные ==========
AFFIRMATIONS = []


# ========== FSM States ==========
class AddTimeState(StatesGroup):
    waiting_for_time = State()


class AddAffirmationState(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()


class EditAffirmationState(StatesGroup):
    waiting_for_id = State()
    waiting_for_text = State()
    waiting_for_photo = State()


class DeleteAffirmationState(StatesGroup):
    waiting_for_id = State()


# ========== БД: init ==========
async def init_db():
    """Инициализация БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица расписания
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_time TEXT NOT NULL UNIQUE
            )
        """)

        # Таблица аффирмаций
        await db.execute("""
            CREATE TABLE IF NOT EXISTS affirmations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                image_id INTEGER NOT NULL
            )
        """)

        # Таблица статистики показов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS affirmation_stats (
                affirmation_id INTEGER PRIMARY KEY,
                shown_count INTEGER DEFAULT 0,
                last_shown_at TEXT,
                FOREIGN KEY (affirmation_id) REFERENCES affirmations(id) ON DELETE CASCADE
            )
        """)

        await db.commit()
        logger.info("✅ База данных инициализирована")


# ========== БД: schedule ==========
async def get_schedule() -> list:
    """Получить расписание постинга"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT post_time FROM schedule ORDER BY post_time")
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def add_schedule_time(post_time: str) -> bool:
    """Добавить время в расписание"""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO schedule (post_time) VALUES (?)", (post_time,))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def delete_schedule_time(post_time: str):
    """Удалить время из расписания"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM schedule WHERE post_time = ?", (post_time,))
        await db.commit()


# ========== БД: affirmations ==========
async def load_affirmations():
    """Загрузить аффирмации из БД в память"""
    global AFFIRMATIONS
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, text, image_id FROM affirmations ORDER BY id")
        rows = await cursor.fetchall()

        AFFIRMATIONS = []
        for row in rows:
            AFFIRMATIONS.append({
                "id": row[0],
                "text": row[1],
                "image_id": row[2]
            })

        if AFFIRMATIONS:
            logger.info(f"✅ Загружено {len(AFFIRMATIONS)} аффирмаций")
        else:
            logger.warning("⚠️ Аффирмации не загружены, список пуст")


async def add_affirmation(text: str, image_id: int) -> int:
    """Добавить аффирмацию в БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO affirmations (text, image_id) VALUES (?, ?)",
            (text, image_id)
        )
        await db.commit()
        aff_id = cursor.lastrowid

        # Создаём запись в статистике
        await db.execute(
            "INSERT INTO affirmation_stats (affirmation_id, shown_count) VALUES (?, 0)",
            (aff_id,)
        )
        await db.commit()

        await load_affirmations()
        return aff_id


async def update_affirmation(aff_id: int, text: Optional[str] = None, image_id: Optional[int] = None):
    """Обновить аффирмацию"""
    async with aiosqlite.connect(DB_PATH) as db:
        if text is not None:
            await db.execute("UPDATE affirmations SET text = ? WHERE id = ?", (text, aff_id))
        if image_id is not None:
            await db.execute("UPDATE affirmations SET image_id = ? WHERE id = ?", (image_id, aff_id))
        await db.commit()

    await load_affirmations()


async def delete_affirmation(aff_id: int):
    """Удалить аффирмацию"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM affirmations WHERE id = ?", (aff_id,))
        await db.commit()

    await load_affirmations()


async def get_all_affirmations() -> list:
    """Получить все аффирмации"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, text, image_id FROM affirmations ORDER BY id")
        rows = await cursor.fetchall()

    return [{"id": r[0], "text": r[1], "image_id": r[2]} for r in rows]


# ========== БД: stats ==========
async def mark_affirmation_shown(aff_id: int):
    """Отметить, что аффирмация показана"""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE affirmation_stats
            SET shown_count = shown_count + 1, last_shown_at = ?
            WHERE affirmation_id = ?
        """, (now, aff_id))
        await db.commit()


async def get_next_affirmation() -> dict:
    """
    Получить следующую аффирмацию для показа.
    Логика:
    1. Выбираем те, что ещё ни разу не показывали (shown_count = 0)
    2. Если таких нет — выбираем ту, что показывали давнее всего (MIN last_shown_at)
    3. Если нет статистики вообще — создаём для всех
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем наличие записей статистики для всех аффирмаций
        cursor = await db.execute("SELECT COUNT(*) FROM affirmations")
        total_affirmations = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM affirmation_stats")
        total_stats = (await cursor.fetchone())[0]

        if total_stats < total_affirmations:
            # Создаём недостающие записи статистики
            await db.execute("""
                INSERT OR IGNORE INTO affirmation_stats (affirmation_id, shown_count)
                SELECT id, 0 FROM affirmations
                WHERE id NOT IN (SELECT affirmation_id FROM affirmation_stats)
            """)
            await db.commit()
            logger.info("✅ Создана статистика для новых аффирмаций")

        # 1. Ищем неотображённые (shown_count = 0)
        cursor = await db.execute("""
            SELECT a.id, a.text, a.image_id
            FROM affirmations a
            JOIN affirmation_stats s ON a.id = s.affirmation_id
            WHERE s.shown_count = 0
            ORDER BY RANDOM()
            LIMIT 1
        """)
        row = await cursor.fetchone()

        if row:
            aff_id, text, image_id = row
            logger.info(f"✅ Выбрана новая аффирмация #{aff_id} (shown_count=0)")
            await mark_affirmation_shown(aff_id)
            return {"id": aff_id, "text": text, "image_id": image_id}

        # 2. Если все уже показывали — сбрасываем счётчики и выбираем самую старую
        cursor = await db.execute("""
            SELECT a.id, a.text, a.image_id, s.last_shown_at
            FROM affirmations a
            JOIN affirmation_stats s ON a.id = s.affirmation_id
            ORDER BY s.last_shown_at ASC, s.shown_count ASC
            LIMIT 1
        """)
        row = await cursor.fetchone()

        if row:
            aff_id, text, image_id, last_shown = row
            logger.info(f"✅ Все аффирмации уже показаны. Сброс и выбор #{aff_id}")

            # Сбрасываем счётчики для всех
            await db.execute("UPDATE affirmation_stats SET shown_count = 0")
            await db.commit()

            await mark_affirmation_shown(aff_id)
            return {"id": aff_id, "text": text, "image_id": image_id}

        # 3. Fallback: вообще нет аффирмаций
        logger.error("❌ Нет аффирмаций в базе!")
        raise ValueError("Нет аффирмаций для публикации")


async def fill_database_with_affirmations():
    """Заполнить БД начальными аффирмациями"""
    initial_affirmations = [
        {"text": "Я достоин(на) любви и уважения.", "image_id": 1},
        {"text": "Моя жизнь наполнена радостью и благодарностью.", "image_id": 2},
        {"text": "Я принимаю себя таким(ой), какой(ая) я есть.", "image_id": 3},
        {"text": "Каждый день я становлюсь лучше.", "image_id": 4},
        {"text": "Я создаю свою реальность своими мыслями и действиями.", "image_id": 5},
        {"text": "Я заслуживаю счастья и успеха.", "image_id": 6},
        {"text": "Мои возможности безграничны.", "image_id": 7},
        {"text": "Я верю в себя и свои способности.", "image_id": 8},
        {"text": "Я притягиваю позитивные изменения в свою жизнь.", "image_id": 9},
        {"text": "Я окружён(а) любовью и поддержкой.", "image_id": 10},
    ]

    for aff in initial_affirmations:
        try:
            await add_affirmation(aff["text"], aff["image_id"])
        except Exception as e:
            logger.warning(f"⚠️ Не удалось добавить аффирмацию: {e}")

    await load_affirmations()
    if AFFIRMATIONS:
        logger.info(f"✅ База данных заполнена {len(AFFIRMATIONS)} аффирмациями")


# ========== Утилиты ==========
def random_pastel_color():
    """Генерация случайного пастельного цвета"""
    r = random.randint(200, 255)
    g = random.randint(200, 255)
    b = random.randint(200, 255)
    return (r, g, b)


def get_affirmation_photo(aff_id: int, aff_text: str) -> str:
    """Получить путь к фото аффирмации или создать заглушку"""
    path = IMAGES_DIR / f"{aff_id}.png"
    if path.exists():
        return str(path)
    
    #fallback_noone_path = IMAGES_DIR / "noone.png"
   # if fallback_noone_path.exists():
      #  return str(fallback_noone_path)
    
    # Создаём fallback изображение
    img = Image.new('RGB', (800, 600), color=random_pastel_color())
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("/app/TTNormsPro-Thin.ttf", 32)
    except:
        font = ImageFont.load_default()
    
    # Функция для переноса текста
    def wrap_text(text: str, max_width: int, font, draw) -> list:
        """Разбивает текст на строки с учетом максимальной ширины"""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            test_width = bbox[2] - bbox[0]
            
            if test_width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    # Если одно слово слишком длинное, всё равно добавляем его
                    lines.append(word)
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
    
    # Параметры текста
    max_text_width = 700  # Отступы по 50px с каждой стороны
    lines = wrap_text(aff_text, max_text_width, font, draw)
    
    # Вычисляем высоту одной строки
    sample_bbox = draw.textbbox((0, 0), "Тестовая строка", font=font)
    line_height = sample_bbox[3] - sample_bbox[1]
    line_spacing = int(line_height * 0.3)  # Межстрочный интервал 30%
    
    # Общая высота текстового блока
    total_text_height = len(lines) * line_height + (len(lines) - 1) * line_spacing
    
    # Начальная позиция Y (центрируем по вертикали)
    start_y = (600 - total_text_height) // 2
    
    # Рисуем каждую строку
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (800 - text_width) // 2
        y = start_y + i * (line_height + line_spacing)
        draw.text((x, y), line, fill="black", font=font)
    
    img.save(path)
    
    return str(path)


async def send_affirmation():
    """Отправка аффирмации в канал"""
    try:
        aff = await get_next_affirmation()
        photo_path = await get_affirmation_photo(aff["image_id"], aff["text"])
        caption = f"✨\n\n\n\nСтавь ❤️ и другой увидит, что он не один\n\n@mentally_fit"
        
        await bot.send_photo(
            CHANNEL_ID,
            photo=FSInputFile(photo_path),
            caption=caption
        )
        
        logger.info(f"✅ Отправлена аффирмация #{aff['id']}: {aff['text'][:30]}...")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки аффирмации: {e}")


async def load_schedule():
    """Загрузка расписания из БД в планировщик"""
    scheduler.remove_all_jobs()
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT post_time FROM schedule ORDER BY post_time")
        times = await cursor.fetchall()
    
    for time_str, in times:
        try:
            t = time.fromisoformat(time_str)
            scheduler.add_job(
                send_affirmation,
                'cron',
                hour=t.hour,
                minute=t.minute,
                id=f"post_{time_str}",
                replace_existing=True
            )
            logger.info(f"✅ Добавлена задача на {time_str}")
        except Exception as e:
            logger.error(f"❌ Ошибка добавления задачи {time_str}: {e}")


# ========== Клавиатуры ==========
def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Управление расписанием", callback_data="schedule_menu")],
        [InlineKeyboardButton(text="📝 Управление аффирмациями", callback_data="affirmations_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🧪 Тест публикации", callback_data="test_post")],
    ])


def schedule_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить время", callback_data="add_time")],
        [InlineKeyboardButton(text="📋 Список времен", callback_data="list_times")],
        [InlineKeyboardButton(text="❌ Удалить время", callback_data="delete_time")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")],
    ])


def affirmations_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аффирмацию", callback_data="add_affirmation")],
        [InlineKeyboardButton(text="📋 Список аффирмаций", callback_data="list_affirmations")],
        [InlineKeyboardButton(text="✏️ Изменить аффирмацию", callback_data="edit_affirmation")],
        [InlineKeyboardButton(text="❌ Удалить аффирмацию", callback_data="delete_affirmation_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")],
    ])


def back_keyboard(callback: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=callback)],
    ])


# ========== Команды ==========
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этому боту.")
        return

    await message.answer(
        "🔥 *Админ-панель бота аффирмаций*\n\n"
        "🔥 *Новая логика*: каждая аффирмация будет показана один раз, "
        "затем цикл начнётся заново.\n\n"
        "Выберите действие:",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    await cb.message.edit_text(
        "🔥 *Админ-панель бота аффирмаций*\n\n"
        "🔥 *Новая логика*: каждая аффирмация будет показана один раз, "
        "затем цикл начнётся заново.\n\n"
        "Выберите действие:",
        reply_markup=admin_keyboard(),
        parse_mode="Markdown"
    )
    await cb.answer()


# ========== Расписание ==========
@router.callback_query(F.data == "schedule_menu")
async def schedule_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "📅 *Управление расписанием*\n\nВыберите действие:",
        reply_markup=schedule_keyboard(),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data == "add_time")
async def add_time_handler(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "⏰ Введите время в формате `HH:MM` (например, 09:30):",
        reply_markup=back_keyboard("schedule_menu"),
        parse_mode="Markdown"
    )
    await state.set_state(AddTimeState.waiting_for_time)
    await cb.answer()


@router.message(AddTimeState.waiting_for_time)
async def process_add_time(message: types.Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        time.fromisoformat(time_str)
        success = await add_schedule_time(time_str)
        if success:
            await load_schedule()
            await message.answer(
                f"✅ Время {time_str} добавлено в расписание!",
                reply_markup=schedule_keyboard()
            )
        else:
            await message.answer(
                f"⚠️ Время {time_str} уже есть в расписании.",
                reply_markup=schedule_keyboard()
            )
    except ValueError:
        await message.answer(
            "❌ Неверный формат времени. Попробуйте снова (например, 09:30):",
            reply_markup=back_keyboard("schedule_menu")
        )
        return

    await state.clear()


@router.callback_query(F.data == "list_times")
async def list_times(cb: CallbackQuery):
    times = await get_schedule()
    if not times:
        await cb.message.edit_text(
            "📋 *Расписание пусто.*",
            reply_markup=schedule_keyboard(),
            parse_mode="Markdown"
        )
    else:
        text = "📋 *Текущее расписание:*\n\n" + "\n".join(f"• {t}" for t in times)
        await cb.message.edit_text(text, reply_markup=schedule_keyboard(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "delete_time")
async def delete_time_handler(cb: CallbackQuery):
    times = await get_schedule()
    if not times:
        await cb.answer("⚠️ Расписание пусто!", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text=t, callback_data=f"del_time_{t}")]
        for t in times
    ]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="schedule_menu")])

    await cb.message.edit_text(
        "❌ *Выберите время для удаления:*",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("del_time_"))
async def confirm_delete_time(cb: CallbackQuery):
    time_str = cb.data.replace("del_time_", "")
    await delete_schedule_time(time_str)
    await load_schedule()
    await cb.message.edit_text(
        f"✅ Время {time_str} удалено из расписания.",
        reply_markup=schedule_keyboard()
    )
    await cb.answer()


# ========== Аффирмации ==========
@router.callback_query(F.data == "affirmations_menu")
async def affirmations_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "📝 *Управление аффирмациями*\n\nВыберите действие:",
        reply_markup=affirmations_keyboard(),
        parse_mode="Markdown"
    )
    await cb.answer()


@router.callback_query(F.data == "add_affirmation")
async def add_affirmation_handler(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "✍️ Отправьте текст новой аффирмации:",
        reply_markup=back_keyboard("affirmations_menu")
    )
    await state.set_state(AddAffirmationState.waiting_for_text)
    await cb.answer()


@router.message(AddAffirmationState.waiting_for_text)
async def process_add_affirmation_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(text=text)
    await message.answer(
        "📷 Теперь отправьте фото для этой аффирмации (или /skip для автогенерации):",
        reply_markup=back_keyboard("affirmations_menu")
    )
    await state.set_state(AddAffirmationState.waiting_for_photo)


@router.message(AddAffirmationState.waiting_for_photo, F.photo)
async def process_add_affirmation_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text")

    # Добавляем аффирмацию с временным image_id
    aff_id = await add_affirmation(text, aff_id := 0)
    await update_affirmation(aff_id, image_id=aff_id)

    # Сохраняем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    await bot.download_file(file.file_path, IMAGES_DIR / f"{aff_id}.png")

    await message.answer(
        f"✅ Аффирмация #{aff_id} добавлена с фото!",
        reply_markup=affirmations_keyboard()
    )
    await state.clear()


@router.message(AddAffirmationState.waiting_for_photo, Command("skip"))
async def skip_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text")

    aff_id = await add_affirmation(text, aff_id := 0)
    await update_affirmation(aff_id, image_id=aff_id)

    await message.answer(
        f"✅ Аффирмация #{aff_id} добавлена без фото (будет автогенерация).",
        reply_markup=affirmations_keyboard()
    )
    await state.clear()


@router.callback_query(F.data == "list_affirmations")
async def list_affirmations(cb: CallbackQuery):
    affirmations = await get_all_affirmations()
    if not affirmations:
        await cb.message.edit_text(
            "📋 *Аффирмации отсутствуют.*",
            reply_markup=affirmations_keyboard(),
            parse_mode="Markdown"
        )
    else:
        text = "📋 *Список аффирмаций:*\n\n"
        for aff in affirmations:
            text += f"#{aff['id']}: {aff['text'][:50]}...\n"
        await cb.message.edit_text(text, reply_markup=affirmations_keyboard(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "edit_affirmation")
async def edit_affirmation_handler(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "✏️ Введите ID аффирмации для редактирования:",
        reply_markup=back_keyboard("affirmations_menu")
    )
    await state.set_state(EditAffirmationState.waiting_for_id)
    await cb.answer()


@router.message(EditAffirmationState.waiting_for_id)
async def process_edit_id(message: types.Message, state: FSMContext):
    try:
        aff_id = int(message.text.strip())
        await state.update_data(aff_id=aff_id)
        await message.answer(
            f"✏️ Введите новый текст для аффирмации #{aff_id} (или /skip для пропуска):",
            reply_markup=back_keyboard("affirmations_menu")
        )
        await state.set_state(EditAffirmationState.waiting_for_text)
    except ValueError:
        await message.answer("❌ Неверный формат ID. Попробуйте снова.")


@router.message(EditAffirmationState.waiting_for_text, Command("skip"))
async def skip_edit_text(message: types.Message, state: FSMContext):
    await message.answer(
        "📷 Отправьте новое фото (или /skip для пропуска):",
        reply_markup=back_keyboard("affirmations_menu")
    )
    await state.set_state(EditAffirmationState.waiting_for_photo)


@router.message(EditAffirmationState.waiting_for_text)
async def process_edit_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    aff_id = data.get("aff_id")

    await update_affirmation(aff_id, text=text)
    await message.answer(
        f"✅ Текст аффирмации #{aff_id} обновлён!\n\n"
        "📷 Отправьте новое фото (или /skip для пропуска):",
        reply_markup=back_keyboard("affirmations_menu")
    )
    await state.set_state(EditAffirmationState.waiting_for_photo)


@router.message(EditAffirmationState.waiting_for_photo, F.photo)
async def process_edit_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    aff_id = data.get("aff_id")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    await bot.download_file(file.file_path, IMAGES_DIR / f"{aff_id}.png")

    await message.answer(
        f"✅ Фото аффирмации #{aff_id} обновлено!",
        reply_markup=affirmations_keyboard()
    )
    await state.clear()


@router.message(EditAffirmationState.waiting_for_photo, Command("skip"))
async def skip_edit_photo(message: types.Message, state: FSMContext):
    await message.answer(
        "✅ Редактирование завершено.",
        reply_markup=affirmations_keyboard()
    )
    await state.clear()


@router.callback_query(F.data == "delete_affirmation_menu")
async def delete_affirmation_menu_handler(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "❌ Введите ID аффирмации для удаления:",
        reply_markup=back_keyboard("affirmations_menu")
    )
    await state.set_state(DeleteAffirmationState.waiting_for_id)
    await cb.answer()


@router.message(DeleteAffirmationState.waiting_for_id)
async def process_delete_affirmation(message: types.Message, state: FSMContext):
    try:
        aff_id = int(message.text.strip())
        await delete_affirmation(aff_id)

        photo_path = IMAGES_DIR / f"{aff_id}.png"
        if photo_path.exists():
            photo_path.unlink()

        await message.answer(
            f"✅ Аффирмация #{aff_id} удалена!",
            reply_markup=affirmations_keyboard()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный формат ID. Попробуйте снова.")


# ========== Статистика ==========
@router.callback_query(F.data == "stats")
async def show_stats(cb: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT a.id, a.text, s.shown_count, s.last_shown_at
            FROM affirmations a
            LEFT JOIN affirmation_stats s ON a.id = s.affirmation_id
            ORDER BY s.shown_count DESC, a.id
        """)
        rows = await cursor.fetchall()

    if not rows:
        await cb.message.edit_text(
            "📊 *Статистика пуста.*",
            reply_markup=back_keyboard("back_to_admin"),
            parse_mode="Markdown"
        )
    else:
        text = "📊 *Статистика аффирмаций:*\n\n"
        for row in rows:
            aff_id, aff_text, shown_count, last_shown = row
            shown_count = shown_count or 0
            last_shown = last_shown or "Никогда"
            text += f"#{aff_id}: {aff_text[:30]}...\n  Показов: {shown_count} | Последний: {last_shown}\n\n"

        await cb.message.edit_text(
            text,
            reply_markup=back_keyboard("back_to_admin"),
            parse_mode="Markdown"
        )
    await cb.answer()


# ========== Тест публикации ==========
@router.callback_query(F.data == "test_post")
async def test_post(cb: CallbackQuery):
    try:
        await send_affirmation()
        await cb.answer("✅ Тестовая аффирмация отправлена!", show_alert=True)
    except Exception as e:
        await cb.answer(f"❌ Ошибка: {e}", show_alert=True)


# ========== Запуск ==========
async def main():
    logger.info("🚀 Запуск бота...")

    await init_db()
    await load_affirmations()

    if not AFFIRMATIONS:
        logger.warning("⚠️ Аффирмации отсутствуют, заполняю базу...")
        await fill_database_with_affirmations()

    await load_schedule()
    scheduler.start()
    logger.info("✅ Планировщик запущен")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
