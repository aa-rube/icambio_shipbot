from aiogram import Bot

async def notify_manager(bot: Bot, courier: dict, text: str):
    chat_id = courier.get("manager_chat_id")
    if chat_id:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            # silently ignore manager notification errors
            pass
