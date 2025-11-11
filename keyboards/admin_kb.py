from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUser

def admin_main_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="➕ Добавить курьера", callback_data="admin:add_user"),
            InlineKeyboardButton(text="➖ Удалить курьера", callback_data="admin:del_user")
        ],
        [InlineKeyboardButton(text="🔄 Синхронизация с Odoo", callback_data="admin:sync_odoo")],
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
        username = c.get("username")
        
        # Создаем список кнопок для этого курьера
        buttons = []
        
        # Слева - кнопка с URL на tg.me/username (если есть username)
        if username:
            # Убираем @ если есть
            username_clean = username.lstrip('@')
            buttons.append(InlineKeyboardButton(
                text=f"👤 {name}",
                url=f"https://t.me/{username_clean}"
            ))
        else:
            # Если нет username, показываем просто имя без ссылки
            buttons.append(InlineKeyboardButton(
                text=f"👤 {name}",
                callback_data="admin:no_action"  # Пустой callback, ничего не делает
            ))
        
        # Справа - кнопка удаления
        buttons.append(InlineKeyboardButton(
            text="❌",
            callback_data=f"admin:confirm_del:{chat_id}"
        ))
        
        kb.append(buttons)
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

def courier_location_kb(chat_id: int, has_route: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if has_route:
        # Если есть маршрут, добавляем обе кнопки в один ряд
        buttons.append([
            InlineKeyboardButton(text="📍 Где курьер?", callback_data=f"admin:show_location:{chat_id}"),
            InlineKeyboardButton(text="🗺 Маршрут сегодня", callback_data=f"admin:show_route:{chat_id}")
        ])
    else:
        # Если нет маршрута, только кнопка локации
        buttons.append([InlineKeyboardButton(text="📍 Где курьер?", callback_data=f"admin:show_location:{chat_id}")])
    # Добавляем кнопку "Активные заказы"
    buttons.append([InlineKeyboardButton(text="📦 Активные заказы", callback_data=f"admin:active_orders:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def courier_location_with_back_kb(chat_id: int, has_route: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if has_route:
        # Если есть маршрут, добавляем обе кнопки в один ряд
        buttons.append([
            InlineKeyboardButton(text="📍 Где курьер?", callback_data=f"admin:show_location:{chat_id}"),
            InlineKeyboardButton(text="🗺 Маршрут сегодня", callback_data=f"admin:show_route:{chat_id}")
        ])
    else:
        # Если нет маршрута, только кнопка локации
        buttons.append([InlineKeyboardButton(text="📍 Где курьер?", callback_data=f"admin:show_location:{chat_id}")])
    # Добавляем кнопку "Активные заказы"
    buttons.append([InlineKeyboardButton(text="📦 Активные заказы", callback_data=f"admin:active_orders:{chat_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:back_from_couriers:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def location_back_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Назад' для возврата к исходному сообщению"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:back_to_courier:{chat_id}")]
    ])

def route_back_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Назад' для возврата к исходному сообщению"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:back_to_courier:{chat_id}")]
    ])

def active_orders_kb(orders: list, chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура со списком активных заказов курьера"""
    buttons = []
    for order in orders:
        external_id = order.get("external_id", "N/A")
        # Объединенная кнопка с номером заказа и карандашом
        buttons.append([
            InlineKeyboardButton(text=f"{external_id} ✏️", callback_data=f"admin:order_edit:{external_id}")
        ])
    # Кнопка "Назад" для возврата к курьеру
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:back_to_courier:{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def order_edit_kb(external_id: str, chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для редактирования заказа"""
    buttons = [
        [InlineKeyboardButton(text="✅ Заказ выполнен", callback_data=f"admin:order_complete:{external_id}")],
        [InlineKeyboardButton(text="🗑 Удалить заказ", callback_data=f"admin:order_delete:{external_id}")],
        [InlineKeyboardButton(text="👤 Назначить курьера", callback_data=f"admin:order_assign_courier:{external_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:active_orders:{chat_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def courier_list_kb(couriers: list, external_id: str) -> InlineKeyboardMarkup:
    """Клавиатура со списком курьеров для назначения заказа"""
    buttons = []
    for courier in couriers:
        name = courier.get("name", "Unknown")
        courier_chat_id = courier.get("tg_chat_id")
        buttons.append([InlineKeyboardButton(
            text=name,
            callback_data=f"admin:assign_courier:{external_id}:{courier_chat_id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:order_edit:{external_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
