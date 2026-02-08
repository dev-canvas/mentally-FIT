import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Импорты из локальных файлов ОДИН РАЗ
from config import BOT_TOKEN, CHANNEL_ID, ADMIN_ID
from database import (init_db, get_setting, set_setting, get_schedule, 
                     add_schedule_time, remove_schedule_time, toggle_schedule_time, get_posts_history)
from scheduler import setup_scheduler, update_scheduler, post_affirmation
from affirmation_generator import generate_affirmation
from image_generator import create_simple_image

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния
WAITING_PROMPT = 1
WAITING_TIME = 2
WAITING_CUSTOM_MESSAGE = 3
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("📝 Изменить промпт", callback_data="change_prompt")],
        [InlineKeyboardButton("⏰ Расписание", callback_data="schedule")],
        [InlineKeyboardButton("✉️ Отправить в канал", callback_data="send_now")],
        [InlineKeyboardButton("📊 История", callback_data="history")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🌟 <b>Affirmation Bot</b>\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "settings":
        prompt = get_setting('prompt')
        model = get_setting('model')
        text = f"⚙️ <b>Настройки</b>\n\n<b>Промпт:</b>\n{prompt}\n\n<b>Модель:</b> {model}"
        keyboard = [[InlineKeyboardButton("📝 Промпт", callback_data="change_prompt")], [InlineKeyboardButton("🔙 Главное", callback_data="back_main")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
    elif query.data == "change_prompt":
        user_states[query.from_user.id] = WAITING_PROMPT
        await query.message.reply_text("📝 Отправь новый промпт:")
        
    elif query.data == "schedule":
        schedule = get_schedule()
        text = "⏰ <b>Расписание:</b>\n\n"
        keyboard = []
        for sid, time, active in schedule:
            status = "✅" if active else "❌"
            text += f"{status} {time}\n"
            keyboard.append([InlineKeyboardButton(f"{status} {time}", callback_data=f"toggle_{sid}")])
        keyboard.extend([[InlineKeyboardButton("➕ Добавить", callback_data="add_time")], [InlineKeyboardButton("🔙 Главное", callback_data="back_main")]])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
    elif query.data == "send_now":
        await query.message.reply_text("Генерирую...")
        await post_affirmation(context.application.bot, CHANNEL_ID)
        await query.message.reply_text("✅ Опубликовано!")
        
    elif query.data == "back_main":
        await start(query.message.reply_text, context)  # Кнопка назад
        
    # Остальные обработчики сокращены для простоты

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    state = user_states.get(user_id)
    if state == WAITING_PROMPT:
        set_setting('prompt', update.message.text)
        user_states[user_id] = None
        await update.message.reply_text("✅ Промпт сохранен!")
    # Остальные состояния...

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    setup_scheduler(app.bot, CHANNEL_ID)
    logger.info("🚀 Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()