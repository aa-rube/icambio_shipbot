import logging
import os
import sys

# Функция для получения домашней директории (может использоваться глобально):
def get_home_directory():
    return os.path.expanduser("~")


# Кастомный форматтер с эмодзи
class EmojiFormatter(logging.Formatter):
    """Форматтер с эмодзи для разных уровней логирования"""
    
    # Эмодзи для разных уровней
    LEVEL_EMOJIS = {
        'DEBUG': '🔍',
        'INFO': 'ℹ️',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🔥',
    }
    
    # Эмодзи для разных модулей/контекстов
    MODULE_EMOJIS = {
        'API': '🌐',
        'ORDERS': '📦',
        'ADMIN': '🔧',
        'SHIFT': '🚚',
        'LOCATION': '📍',
        'WEBHOOK': '🔗',
        'ODOO': '🔌',
        'REDIS': '💾',
        'MONGO': '🗄️',
        'BOT': '🤖',
    }
    
    def format(self, record):
        # Добавляем эмодзи для уровня
        level_emoji = self.LEVEL_EMOJIS.get(record.levelname, '')
        
        # Определяем контекст по имени модуля или сообщению
        context_emoji = ''
        message = record.getMessage()
        module_name = record.name.split('.')[-1]
        
        # Проверяем сообщение на наличие префиксов
        if '[API]' in message:
            context_emoji = self.MODULE_EMOJIS.get('API', '')
        elif '[ORDERS]' in message:
            context_emoji = self.MODULE_EMOJIS.get('ORDERS', '')
        elif '[ADMIN]' in message or 'admin' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('ADMIN', '')
        elif '[SHIFT]' in message or 'shift' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('SHIFT', '')
        elif '[LOCATION]' in message or 'location' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('LOCATION', '')
        elif '[WEBHOOK]' in message or 'webhook' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('WEBHOOK', '')
        elif '[ODOO]' in message or 'odoo' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('ODOO', '')
        elif '[REDIS]' in message or 'redis' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('REDIS', '')
        elif '[MONGO]' in message or 'mongo' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('MONGO', '')
        elif '[BOT]' in message or 'bot' in module_name.lower():
            context_emoji = self.MODULE_EMOJIS.get('BOT', '')
        
        # Формируем эмодзи строку
        emoji_prefix = f"{level_emoji} {context_emoji}".strip()
        if emoji_prefix:
            emoji_prefix += " "
        
        # Обновляем сообщение с эмодзи
        record.msg = f"{emoji_prefix}{record.msg}"
        
        return super().format(record)


# Настройка логов
LOG_PATH = os.path.join(get_home_directory(), "logs", "odoo_ship_bot.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Получаем корневой логгер
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Удаляем существующие обработчики, если есть
logger.handlers.clear()

# Формат для файла (без эмодзи для читаемости)
file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Формат для консоли (с эмодзи и цветами)
console_formatter = EmojiFormatter(
    '%(asctime)s │ %(levelname)-8s │ %(filename)s:%(lineno)d │ %(funcName)s │ %(message)s',
    datefmt='%H:%M:%S'
)

# Обработчик для файла
file_handler = logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Обработчик для консоли
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(console_formatter)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
logger.addHandler(console_handler)
