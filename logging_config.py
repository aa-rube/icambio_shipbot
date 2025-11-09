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

# Фильтр для исключения библиотечных логов
class LibraryLogFilter(logging.Filter):
    """Фильтр, который скрывает DEBUG логи от библиотек"""
    
    # Список модулей библиотек, которые нужно скрыть
    LIBRARY_MODULES = {
        'pymongo', 'motor', 'aiogram', 'uvicorn', 'aiohttp', 
        'asyncio', 'urllib3', 'httpx', 'httpcore',
        'pymongo.serverSelection', 'pymongo.connection', 
        'pymongo.topology', 'pymongo.pool', 'pymongo.network',
        'aiogram.event', 'aiogram.dispatcher', 'aiogram.client',
        'uvicorn.access', 'uvicorn.error',
        'aiohttp.client', 'aiohttp.server', 'aiohttp.web', 'aiohttp.connector'
    }
    
    def filter(self, record):
        # Пропускаем только WARNING и выше от библиотек
        if record.levelno >= logging.WARNING:
            return True
        
        # Проверяем имя функции (для случаев, когда логи идут через кастомные обработчики)
        func_name = getattr(record, 'funcName', '')
        if func_name in ['_debug_log', '_log', '_info_log', '_warning_log', '_error_log']:
            # Это внутренние логи библиотек, скрываем их
            return False
        
        # Проверяем имя логгера
        logger_name = record.name
        for lib_module in self.LIBRARY_MODULES:
            if logger_name.startswith(lib_module):
                return False
        
        # Проверяем имя файла (для случаев, когда логи идут через корневой логгер)
        filename = record.filename if hasattr(record, 'filename') else ''
        if filename:
            # Скрываем логи из библиотечных файлов
            lib_file_names = ['pymongo', 'motor', 'aiogram', 'uvicorn', 'aiohttp', 'logger.py']
            if any(lib in filename.lower() for lib in lib_file_names):
                # Но пропускаем наш собственный logger.py, если он не из библиотеки
                if 'utils/logger.py' in filename or 'logging_config.py' in filename:
                    return True
                return False
        
        # Проверяем сообщение на наличие признаков библиотечных логов
        message = record.getMessage() if hasattr(record, 'getMessage') else str(record.msg)
        if message:
            # Скрываем логи с типичными сообщениями библиотек
            lib_messages = [
                'topology monitoring', 'topology description', 'server selection',
                'connection pool', 'connection checkout', 'connection checked',
                'command started', 'command succeeded', 'server heartbeat',
                'waiting for suitable server'
            ]
            if any(lib_msg.lower() in message.lower() for lib_msg in lib_messages):
                return False
        
        # Пропускаем все остальные логи
        return True

# Применяем фильтр к обработчикам
library_filter = LibraryLogFilter()
file_handler.addFilter(library_filter)
console_handler.addFilter(library_filter)

# Отключаем DEBUG логи от библиотек - оставляем только WARNING и выше
# MongoDB драйверы
logging.getLogger('pymongo').setLevel(logging.WARNING)
logging.getLogger('motor').setLevel(logging.WARNING)
logging.getLogger('pymongo.serverSelection').setLevel(logging.WARNING)
logging.getLogger('pymongo.connection').setLevel(logging.WARNING)
logging.getLogger('pymongo.topology').setLevel(logging.WARNING)
logging.getLogger('pymongo.pool').setLevel(logging.WARNING)
logging.getLogger('pymongo.network').setLevel(logging.WARNING)

# Aiogram (Telegram bot)
logging.getLogger('aiogram').setLevel(logging.WARNING)
logging.getLogger('aiogram.event').setLevel(logging.WARNING)
logging.getLogger('aiogram.dispatcher').setLevel(logging.WARNING)
logging.getLogger('aiogram.client').setLevel(logging.WARNING)

# Uvicorn (FastAPI server)
logging.getLogger('uvicorn').setLevel(logging.WARNING)
logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
logging.getLogger('uvicorn.error').setLevel(logging.WARNING)

# Aiohttp (используется aiogram)
logging.getLogger('aiohttp').setLevel(logging.WARNING)
logging.getLogger('aiohttp.client').setLevel(logging.WARNING)
logging.getLogger('aiohttp.server').setLevel(logging.WARNING)
logging.getLogger('aiohttp.web').setLevel(logging.WARNING)
logging.getLogger('aiohttp.connector').setLevel(logging.WARNING)

# Другие библиотеки
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
