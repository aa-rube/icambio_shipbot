from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import DEV_CHAT_ID
from db.mongo import get_db
import logging

router = Router()
logger = logging.getLogger(__name__)

class ReportStates(StatesGroup):
    waiting_report_text = State()

@router.message(F.text == "/report")
@router.message(F.text == "report")
async def cmd_report(message: Message, state: FSMContext):
    """Команда для отправки сообщения разработчику о проблемах"""
    logger.info(f"[REPORT] 📝 Пользователь {message.from_user.id} использует команду /report")
    
    # Сбрасываем предыдущее состояние FSM, если оно было установлено
    await state.clear()
    
    if not DEV_CHAT_ID:
        await message.answer(
            "❌ Функция отправки сообщений разработчику временно недоступна.\n"
            "Пожалуйста, свяжитесь с администратором другим способом."
        )
        return
    
    instruction = (
        "📝 Отправка сообщения разработчику\n\n"
        "Опишите проблему, с которой вы столкнулись:\n"
        "• Что произошло?\n"
        "• Когда это случилось?\n"
        "• Что вы делали перед этим?\n\n"
        "Отправьте ваше сообщение одним текстом."
    )
    
    await message.answer(instruction)
    await state.set_state(ReportStates.waiting_report_text)

@router.message(ReportStates.waiting_report_text)
async def process_report(message: Message, state: FSMContext, bot: Bot):
    """Обработка текста сообщения для разработчика"""
    # Если пользователь отправил команду, сбрасываем состояние
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    
    logger.info(f"[REPORT] 📨 Пользователь {message.from_user.id} отправил сообщение разработчику")
    
    if not DEV_CHAT_ID:
        await message.answer("❌ Ошибка: DEV_CHAT_ID не установлен")
        await state.clear()
        return
    
    db = await get_db()
    courier = await db.couriers.find_one({"tg_chat_id": message.chat.id})
    
    courier_name = courier.get("name", "Неизвестный") if courier else "Неизвестный"
    courier_username = courier.get("username", "—") if courier else "—"
    courier_id = message.from_user.id
    
    # Формируем сообщение для разработчика
    report_text = (
        f"🐛 Сообщение от курьера\n\n"
        f"👤 Курьер: {courier_name}\n"
        f"📱 Username: @{courier_username}\n"
        f"🆔 ID: {courier_id}\n\n"
        f"📝 Сообщение:\n{message.text}"
    )
    
    try:
        await bot.send_message(DEV_CHAT_ID, report_text)
        logger.info(f"[REPORT] ✅ Сообщение отправлено разработчику {DEV_CHAT_ID}")
        await message.answer(
            "✅ Ваше сообщение отправлено разработчику.\n"
            "Спасибо за обратную связь!"
        )
    except Exception as e:
        logger.error(f"[REPORT] ❌ Ошибка отправки сообщения разработчику: {e}", exc_info=True)
        await message.answer(
            "❌ Произошла ошибка при отправке сообщения.\n"
            "Пожалуйста, попробуйте позже или свяжитесь с администратором другим способом."
        )
    
    await state.clear()

