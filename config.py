import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# API настройки
MLVOCA_API_URL = "https://api.mlvoca.com/v1/chat/completions"
MLVOCA_MODELS = {
    'tinyllama': 'tinyllama',
    'deepseek': 'deepseek-r1:1.5b'
}

# Папки
DATA_DIR = 'data'
IMAGES_DIR = 'images'