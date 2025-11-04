from aiogram import Bot
from config import MANAGER_CHAT_ID
import logging

logger = logging.getLogger(__name__)

async def notify_manager(bot: Bot, courier: dict, text: str):
    if MANAGER_CHAT_ID:
        try:
            await bot.send_message(MANAGER_CHAT_ID, text)
            logger.info(f"Notified manager {MANAGER_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to notify manager: {e}")
