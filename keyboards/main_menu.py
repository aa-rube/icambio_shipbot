from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

def main_menu(is_on_shift: bool = False) -> InlineKeyboardMarkup:
    if is_on_shift:
        kb = [
            [InlineKeyboardButton(text="🔴 Закончить смену", callback_data="shift:end")],
            [InlineKeyboardButton(text="📋 Мои заказы", callback_data="orders:list")],
        ]
    else:
        kb = [
            [InlineKeyboardButton(text="🟢 Начать смену", callback_data="shift:start")],
            [InlineKeyboardButton(text="📋 Мои заказы", callback_data="orders:list")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
