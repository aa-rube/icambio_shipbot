"""
Утилита для работы с тестовыми заказами.
Тестовые заказы имеют отрицательный external_id (например, "-301").
Для тестовых заказов:
- Статус оплаты автоматически становится "PAID"
- Никакие данные не отправляются во внешние системы (webhooks, Odoo)
"""

def is_test_order(external_id: str) -> bool:
    """
    Проверяет, является ли заказ тестовым.
    Тестовые заказы имеют отрицательный external_id (начинается с "-").
    
    Args:
        external_id: ID заказа (строка)
        
    Returns:
        True если заказ тестовый, False в противном случае
    """
    if not external_id:
        return False
    
    # Проверяем, начинается ли external_id с минуса (отрицательное число)
    return str(external_id).strip().startswith("-")

def ensure_test_order_payment_status(order: dict) -> dict:
    """
    Для тестовых заказов автоматически устанавливает статус оплаты "PAID".
    Если заказ не тестовый, возвращает заказ без изменений.
    
    Args:
        order: Словарь с данными заказа
        
    Returns:
        Обновленный заказ (если тестовый) или исходный заказ
    """
    external_id = order.get("external_id")
    
    # Если заказ тестовый, автоматически устанавливаем статус оплаты "PAID"
    if is_test_order(external_id):
        order["payment_status"] = "PAID"
    
    return order

