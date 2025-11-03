from aiogram.utils.keyboard import InlineKeyboardBuilder

# Callback data formats:
# order:go:{external_id}
# order:later:{external_id}
# order:done:{external_id}
# order:problem:{external_id}

def new_order_kb(external_id: str):
    b = InlineKeyboardBuilder()
    b.button(text="▶ Поехали", callback_data=f"order:go:{external_id}")
    b.button(text="⏱ Возьму позже", callback_data=f"order:later:{external_id}")
    b.adjust(2)
    return b.as_markup()

def in_transit_kb(external_id: str):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Заказ выполнен", callback_data=f"order:done:{external_id}")
    b.button(text="⚠ Проблема с заказом", callback_data=f"order:problem:{external_id}")
    b.adjust(2)
    return b.as_markup()
