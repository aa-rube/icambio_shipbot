from aiogram import Router
from aiogram.types import ErrorEvent

router = Router()

@router.errors()
async def on_error(event: ErrorEvent):
    # Log only; avoid leaking details to users
    try:
        # event.exception, event.update
        pass
    except Exception:
        pass
