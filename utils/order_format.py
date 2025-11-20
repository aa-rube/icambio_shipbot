import re

def clean_html_notes(notes: str) -> str:
    """
    Очищает HTML-теги из notes, оставляя только поддерживаемые Telegram теги.
    Telegram поддерживает: <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <tg-spoiler>
    Удаляет все остальные теги, включая <p>, <div>, <span> и т.д.
    """
    if not notes:
        return ""
    
    # Удаляем неподдерживаемые HTML-теги, но сохраняем их содержимое
    # Сначала заменяем <p> и </p> на переносы строк
    notes = re.sub(r'<p[^>]*>', '\n', notes, flags=re.IGNORECASE)
    notes = re.sub(r'</p>', '\n', notes, flags=re.IGNORECASE)
    
    # Удаляем другие неподдерживаемые теги, но сохраняем содержимое
    # Разрешаем только поддерживаемые Telegram теги
    allowed_tags = ['b', 'i', 'u', 's', 'code', 'pre', 'a', 'tg-spoiler']
    
    # Удаляем все теги, кроме разрешенных
    pattern = r'<(?!\/?(?:' + '|'.join(allowed_tags) + r')\b)[^>]+>'
    notes = re.sub(pattern, '', notes, flags=re.IGNORECASE)
    
    # Очищаем множественные переносы строк
    notes = re.sub(r'\n{3,}', '\n\n', notes)
    
    # Убираем пробелы в начале и конце
    notes = notes.strip()
    
    return notes

def format_order_text(order: dict) -> str:
    """
    Унифицированное форматирование заказа для всех сообщений.
    
    Args:
        order: Словарь с данными заказа
        
    Returns:
        Отформатированный текст заказа в формате HTML для Telegram
    """
    status_emoji = {"waiting": "⏳", "in_transit": "🚗", "done": "✅", "cancelled": "❌"}
    status_text = {"waiting": "Ожидает", "in_transit": "В пути", "done": "Выполнен", "cancelled": "Отменен"}
    
    # Маппинг статуса оплаты на русский язык для курьеров
    payment_status_text = {
        'PAID': 'Оплачен',
        'NOT_PAID': 'Не оплачен',
        'REFUND': 'Отмена заказа'
    }
    
    priority_emoji = "🔴" if order.get("priority", 0) >= 5 else "🟡" if order.get("priority", 0) >= 3 else "⚪"
    
    # Номер заказа в самом начале
    text = f"📦 Заказ: {order.get('external_id', '—')}\n\n"
    text += f"{status_emoji.get(order.get('status', 'waiting'), '⏳')} Статус: {status_text.get(order.get('status', 'waiting'), 'Ожидает')}\n\n"
    text += f"<code>{order.get('address', '—')}</code>\n\n"
    
    if order.get("map_url"):
        text += f"🗺 <a href='{order['map_url']}'>Карта</a>\n\n"
    
    # Используем маппинг для статуса оплаты
    payment_status = order.get('payment_status', 'NOT_PAID')
    payment_status_ru = payment_status_text.get(payment_status, payment_status)
    
    # Выбираем эмодзи в зависимости от статуса оплаты
    if payment_status == 'NOT_PAID':
        payment_emoji = "❌❌❌"
    elif payment_status == 'PAID':
        payment_emoji = "✅✅✅"
    elif payment_status == 'REFUND':
        payment_emoji = "◼️◼️◼️"
    else:
        payment_emoji = "💳"  # Для других статусов
    
    text += f"{payment_emoji} {payment_status_ru} | {priority_emoji} Приоритет: {order.get('priority', 0)}\n"
    
    if order.get("delivery_time"):
        text += f"⏰ {order['delivery_time']}\n"
    
    client = order.get('client', {})
    text += f"👤 {client.get('name', '—')} | 📞 {client.get('phone', '—')}\n"
    
    if client.get('tg'):
        text += f"@{client['tg'].lstrip('@')}\n"
    
    if order.get("notes"):
        cleaned_notes = clean_html_notes(order['notes'])
        if cleaned_notes:
            text += f"\n📝 {cleaned_notes}\n"
    
    if order.get("brand") or order.get("source"):
        text += "\n"
        if order.get("brand"):
            text += f"🏷 {order['brand']}"
        if order.get("source"):
            text += f" | 📊 {order['source']}"
    
    return text

