from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database import get_schedule
from affirmation_generator import generate_affirmation
from image_generator import create_simple_image
from database import save_post_history
import logging

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def post_affirmation(bot, channel_id):
    """Публикация аффирмации в канал"""
    try:
        # Генерируем аффирмацию
        affirmation = await generate_affirmation()
        logger.info(f"Сгенерирована аффирмация: {affirmation}")
        
        # Создаем картинку
        image_path = create_simple_image(affirmation)
        logger.info(f"Создана картинка: {image_path}")
        
        # Отправляем в канал
        with open(image_path, 'rb') as photo:
            await bot.send_photo(
                chat_id=channel_id,
                photo=photo,
                caption=f"✨ {affirmation}"
            )
        
        # Сохраняем в историю
        save_post_history(affirmation, image_path)
        logger.info("Аффирмация успешно опубликована")
        
    except Exception as e:
        logger.error(f"Ошибка при публикации аффирмации: {e}")

def setup_scheduler(bot, channel_id):
    """Настройка расписания"""
    schedule = get_schedule()
    
    # Очищаем старые задачи
    scheduler.remove_all_jobs()
    
    # Добавляем задачи по расписанию
    for schedule_id, time, active in schedule:
        if active:
            hour, minute = map(int, time.split(':'))
            scheduler.add_job(
                post_affirmation,
                CronTrigger(hour=hour, minute=minute),
                args=[bot, channel_id],
                id=f'post_{schedule_id}',
                replace_existing=True
            )
            logger.info(f"Добавлена задача на {time}")
    
    if not scheduler.running:
        scheduler.start()
        logger.info("Планировщик запущен")

def update_scheduler(bot, channel_id):
    """Обновление расписания"""
    setup_scheduler(bot, channel_id)