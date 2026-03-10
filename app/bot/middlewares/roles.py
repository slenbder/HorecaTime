import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from app.services.roles_cache import RolesCacheService

from config import SUPERADMIN_IDS, ADMIN_HALL_IDS, ADMIN_BAR_IDS, ADMIN_KITCHEN_IDS, DEVELOPER_ID

logger = logging.getLogger(__name__)


class RoleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:

        telegram_id = None
        if isinstance(event, Message):
            telegram_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            telegram_id = event.from_user.id

        if telegram_id is None:
            return await handler(event, data)

        role = "guest"
        user_data = None

        cached_data = RolesCacheService.get_user_role(telegram_id)
        if cached_data:
            role = cached_data["role"]
            user_data = cached_data
            logger.debug(f"Пользователь {telegram_id} найден в кеше: {role}")
        else:
            if DEVELOPER_ID and telegram_id == DEVELOPER_ID:
                role = "developer"
            elif telegram_id in SUPERADMIN_IDS:
                role = "superadmin"
            elif telegram_id in ADMIN_HALL_IDS:
                role = "admin_hall"
            elif telegram_id in ADMIN_BAR_IDS:
                role = "admin_bar"
            elif telegram_id in ADMIN_KITCHEN_IDS:
                role = "admin_kitchen"

        data["user_role"] = role
        data["user_data"] = user_data

        return await handler(event, data)