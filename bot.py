import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN, CHANNEL_ID, ADMIN_ID
from database import init_db, get_setting, set_setting, get_schedule, add_schedule_time, remove_schedule_time, toggle_schedule_time, get_posts_history
from scheduler import setup_scheduler, update_scheduler, post_affirmation
from affirmation_generator import generate_affirmation
from image_generator import create_simple_image

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для FSM
WAITING_PROMPT = 1
WAITING_TIME = 2
WAITING_CUSTOM_MESSAGE = 3

user_states = {}

def admin_only(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ У вас нет доступа к этой команде.")
            return
        return await func(update, context)
    return wrapper

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    keyboard = [
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("📝 Изменить промпт", callback_data="change_prompt")],
        [InlineKeyboardButton("⏰ Расписание", callback_data="schedule")],
        [InlineKeyboardButton("✉️ Отправить в канал", callback_data="send_now")],
        [InlineKeyboardButton("📊 История", callback_data="history")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌟 Affirmation Bot\n\n"
        "Бот для автоматической генерации и публикации аффирмаций в канал.\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "settings":
        await show_settings(query, context)
    elif query.data == "change_prompt":
        await start_change_prompt(query, context)
    elif query.data == "schedule":
        await show_schedule(query, context)
    elif query.data == "add_time":
        await start_add_time(query, context)
    elif query.data.startswith("remove_"):
        schedule_id = int(query.data.split("_")[1])
        remove_schedule_time(schedule_id)
        update_scheduler(context.application.bot, CHANNEL_ID)
        await show_schedule(query, context)
    elif query.data.startswith("toggle_"):
        schedule_id = int(query.data.split("_")[1])
        toggle_schedule_time(schedule_id)
        update_scheduler(context.application.bot, CHANNEL_ID)
        await show_schedule(query, context)
    elif query.data == "send_now":
        await query.message.reply_text("Генерирую и отправляю аффирмацию...")
        await post_affirmation(context.application.bot, CHANNEL_ID)
        await query.message.reply_text("✅ Аффирмация опубликована!")
    elif query.data == "send_custom":
        await start_custom_message(query, context)
    elif query.data == "history":
        await show_history(query, context)
    elif query.data == "back_main":
        keyboard = [
            [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
            [InlineKeyboardButton("📝 Изменить промпт", callback_data="change_prompt")],
            [InlineKeyboardButton("⏰ Расписание", callback_data="schedule")],
            [InlineKeyboardButton("✉️ Отправить в канал", callback_data="send_now")],
            [InlineKeyboardButton("📊 История", callback_data="history")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            "🌟 Affirmation Bot\n\nВыберите действие:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def show_settings(query, context):
    """Показать настройки"""
    prompt = get_setting('prompt')
    model = get_setting('model')
    
    text = (
        "⚙️ Текущие настройки\n\n"
        f"Промпт:\n{prompt}\n\n"
        f"Модель: {model}\n\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Изменить промпт", callback_data="change_prompt")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def start_change_prompt(query, context):
    """Начать изменение промпта"""
    user_states[query.from_user.id] = WAITING_PROMPT
    await query.message.reply_text(
        "📝 Отправьте новый промпт для генерации аффирмаций.\n\n"
        "Текущий промпт:\n" + get_setting('prompt')
    )

async def show_schedule(query, context):
    """Показать расписание"""
    schedule = get_schedule()
    
    text = "⏰ Расписание постов\n\n"
    keyboard = []
    
    for schedule_id, time, active in schedule:
        status = "✅" if active else "❌"
        text += f"{status} {time}\n"
        keyboard.append([
            InlineKeyboardButton(f"{status} {time}", callback_data=f"toggle_{schedule_id}"),
            InlineKeyboardButton("🗑", callback_data=f"remove_{schedule_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить время", callback_data="add_time")])
    keyboard.append([InlineKeyboardButton("✉️ Свое сообщение", callback_data="send_custom")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def start_add_time(query, context):
    """Начать добавление времени"""
    user_states[query.from_user.id] = WAITING_TIME
    await query.message.reply_text(
        "⏰ Отправьте время в формате ЧЧ:ММ\n"
        "Например: 09:00"
    )

async def start_custom_message(query, context):
    """Начать отправку своего сообщения"""
    user_states[query.from_user.id] = WAITING_CUSTOM_MESSAGE
    await query.message.reply_text(
        "✉️ Отправьте текст, который хотите опубликовать в канале.\n"
        "Можете отправить текст или текст с фото."
    )

async def show_history(query, context):
    """Показать историю постов"""
    history = get_posts_history(5)
    
    text = "📊 Последние 5 постов:\n\n"
    
    for affirmation, posted_at in history:
        text += f"• {affirmation}\n  {posted_at}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        return
    
    state = user_states.get(user_id)
    
    if state == WAITING_PROMPT:
        new_prompt = update.message.text
        set_setting('prompt', new_prompt)
        user_states[user_id] = None
        await update.message.reply_text("✅ Промпт обновлен!")
        
    elif state == WAITING_TIME:
        time = update.message.text.strip()
        if len(time.split(':')) == 2:
            try:
                hour, minute = map(int, time.split(':'))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    add_schedule_time(time)
                    update_scheduler(context.application.bot, CHANNEL_ID)
                    user_states[user_id] = None
                    await update.message.reply_text(f"✅ Время {time} добавлено в расписание!")
                else:
                    await update.message.reply_text("❌ Неверный формат времени. Попробуйте еще раз.")
            except:
                await update.message.reply_text("❌ Неверный формат времени. Попробуйте еще раз.")
        else:
            await update.message.reply_text("❌ Неверный формат времени. Используйте ЧЧ:ММ")
            
    elif state == WAITING_CUSTOM_MESSAGE:
        # Отправка своего сообщения в канал
        try:
            if update.message.photo:
                photo = update.message.photo[-1]
                caption = update.message.caption or ""
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=photo.file_id,
                    caption=caption
                )
            else:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=update.message.text
                )
            user_states[user_id] = None
            await update.message.reply_text("✅ Сообщение отправлено в канал!")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при отправке: {e}")

def main():
    """Запуск бота"""
    # Инициализация БД
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    
    # Настройка планировщика
    setup_scheduler(application.bot, CHANNEL_ID)
    
    # Запуск
    logger.info("Бот запущен")
    application.run_polling()

if __name__ == '__main__':
    main()