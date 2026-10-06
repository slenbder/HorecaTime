import asyncio
import logging
from typing import TYPE_CHECKING, Optional, cast

import aiohttp
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 4.0
CONNECT_RETRIES = 3


class ResilientAiohttpSession(AiohttpSession):
    """Сессия aiogram с коротким таймаутом установки TCP и повтором при его провале.

    Зачем подкласс: с сервера часть новых соединений к api.telegram.org не
    устанавливается (SYN без ответа). Штатная сессия ждёт целиком общий таймаут
    (60 с) и не повторяет. Таймаут сессии тут не помогает: aiogram передаёт
    в session.post число, и пер-запросный таймаут ЗАМЕНЯЕТ таймаут сессии,
    поэтому sock_connect приходится задавать в ClientTimeout внутри make_request.

    Повторяются только ошибки установки соединения (запрос на сервер не ушёл,
    повтор безопасен даже для sendMessage). Таймаут ответа и обрыв соединения
    после отправки не повторяются.

    Метод make_request дублирует часть make_request из aiogram==3.13.1 и
    пересматривается при обновлении aiogram (см. канарейку в
    tests/test_telegram_session.py).
    """

    async def make_request(
        self, bot: "Bot", method: TelegramMethod[TelegramType], timeout: Optional[int] = None
    ) -> TelegramType:
        session = await self.create_session()

        url = self.api.api_url(token=bot.token, method=method.__api_method__)
        client_timeout = aiohttp.ClientTimeout(
            total=self.timeout if timeout is None else timeout,
            sock_connect=CONNECT_TIMEOUT,
        )

        for attempt in range(1, CONNECT_RETRIES + 1):
            form = self.build_form_data(bot=bot, method=method)
            try:
                async with session.post(url, data=form, timeout=client_timeout) as resp:
                    raw_result = await resp.text()
                break
            except (aiohttp.ConnectionTimeoutError, aiohttp.ClientConnectorError) as e:
                if attempt < CONNECT_RETRIES:
                    logger.warning(
                        "Telegram: нет соединения (%s), метод=%s, попытка %d/%d",
                        type(e).__name__,
                        method.__api_method__,
                        attempt,
                        CONNECT_RETRIES,
                    )
                    continue
                raise TelegramNetworkError(
                    method=method,
                    message=f"{type(e).__name__}: соединение не установлено",
                )
            except asyncio.TimeoutError:
                raise TelegramNetworkError(method=method, message="Request timeout error")
            except aiohttp.ClientError as e:
                raise TelegramNetworkError(method=method, message=f"{type(e).__name__}: {e}")

        response = self.check_response(
            bot=bot, method=method, status_code=resp.status, content=raw_result
        )
        return cast(TelegramType, response.result)


async def wait_for_telegram(bot: "Bot", attempts: int = 6, delay: float = 2.0) -> None:
    """Прогрев getMe перед стартом поллинга: результат кэшируется в Bot.me().

    Штатный _polling вызывает bot.me() вне try, и один сбой роняет процесс.
    """
    for attempt in range(1, attempts + 1):
        try:
            await bot.me()
            return
        except TelegramNetworkError as e:
            if attempt >= attempts:
                raise
            logger.warning(
                "Telegram: getMe не удался (%s), попытка %d/%d",
                type(e).__name__,
                attempt,
                attempts,
            )
            await asyncio.sleep(delay)
