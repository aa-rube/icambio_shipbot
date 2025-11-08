from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUser

def admin_main_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="➕ Добавить курьера", callback_data="admin:add_user"),
            InlineKeyboardButton(text="➖ Удалить курьера", callback_data="admin:del_user")
        ],
        [InlineKeyboardButton(text="🚚 Курьеры на смене", callback_data="admin:on_shift")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_to_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])

def request_user_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="👤 Выбрать пользователя",
                request_user=KeyboardButtonRequestUser(request_id=1, user_is_bot=False)
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def user_list_kb(couriers: list) -> InlineKeyboardMarkup:
    kb = []
    for c in couriers:
        name = c.get("name", "Unknown")
        chat_id = c.get("tg_chat_id")
        kb.append([InlineKeyboardButton(
            text=f"🗑 {name}",
            url=f"tg://user?id={chat_id}",
        ), InlineKeyboardButton(
            text="❌",
            callback_data=f"admin:confirm_del:{chat_id}"
        )])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def confirm_delete_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin:delete:{chat_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:del_user")]
    ])

def broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Всем курьерам", callback_data="admin:bc:all")],
        [InlineKeyboardButton(text="🟢 На смене", callback_data="admin:bc:on_shift")],
        [InlineKeyboardButton(text="🔴 Не на смене", callback_data="admin:bc:off_shift")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])

def courier_location_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Где курьер?", callback_data=f"admin:location:{chat_id}")]
    ])
