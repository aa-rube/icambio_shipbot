import logging
import os

def get_home_directory():
    return os.path.expanduser("~")

LOG_PATH = os.path.join(get_home_directory(), "logs", "shipbot.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    if logger.handlers:
        return
    logger.setLevel(level)
    
    # File handler
    file_handler = logging.FileHandler(LOG_PATH, mode='a')
    file_handler.setLevel(level)
    file_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
