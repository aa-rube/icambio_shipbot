import logging
import os

# Функция для получения домашней директории (может использоваться глобально):
def get_home_directory():
    return os.path.expanduser("~")


# Настройка логов
LOG_PATH = os.path.join(get_home_directory(), "logs", "odoo_ship_bot.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Базовая конфигурация: логи записываются в файл
# Уровень DEBUG для подробного логирования всех шагов
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(funcName)s: %(message)s',
    filemode='a'
)

# Получаем корневой логгер
logger = logging.getLogger()

# Создаём обработчик для вывода в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)  # DEBUG для подробного логирования
console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(funcName)s: %(message)s')
console_handler.setFormatter(console_formatter)

# Добавляем консольный обработчик к логгеру
logger.addHandler(console_handler)
