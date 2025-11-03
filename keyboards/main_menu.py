from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🟢 Начать смену"), KeyboardButton(text="🔴 Закончить смену")],
        [KeyboardButton(text="📋 Мои заказы")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def request_location_kb() -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text="📍 Отправить местоположение", request_location=True)]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
