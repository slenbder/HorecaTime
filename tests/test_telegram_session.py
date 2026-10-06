"""ResilientAiohttpSession и wait_for_telegram: без сети, fake create_session/post."""
import asyncio

import aiogram
import aiohttp
import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError

from app.utils import telegram_session
from app.utils.telegram_session import ResilientAiohttpSession, wait_for_telegram

OK_BODY = '{"ok": true, "result": {"id": 1, "is_bot": true, "first_name": "Bot", "username": "bot"}}'


class FakeResponse:
    status = 200

    async def text(self):
        return OK_BODY


class FakePost:
    def __init__(self, outcome):
        self.outcome = outcome

    async def __aenter__(self):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return FakeResponse()

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append(timeout)
        if isinstance(data, aiohttp.FormData):
            data()  # как ClientRequest: обработка формы до установки соединения
        return FakePost(self.outcomes.pop(0))


def _conn_key():
    from aiohttp.client_reqrep import ConnectionKey
    return ConnectionKey("h", 443, True, None, None, None, None)


def _connector_error():
    return aiohttp.ClientConnectorError(_conn_key(), OSError("boom"))


def _make(outcomes):
    sess = ResilientAiohttpSession()
    fake = FakeSession(outcomes)

    async def create_session():
        return fake

    sess.create_session = create_session
    return Bot(token="123456:TEST", session=sess), fake


@pytest.mark.asyncio
async def test_two_connect_timeouts_then_success():
    bot, fake = _make([aiohttp.ConnectionTimeoutError(), aiohttp.ConnectionTimeoutError(), None])
    user = await bot.get_me()
    assert user.id == 1
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_three_connect_timeouts_raise():
    bot, fake = _make([aiohttp.ConnectionTimeoutError()] * 3)
    with pytest.raises(TelegramNetworkError) as ei:
        await bot.get_me()
    assert len(fake.calls) == 3
    assert "соединение не установлено" in ei.value.message


@pytest.mark.asyncio
async def test_connector_error_is_retried():
    bot, fake = _make([_connector_error(), None])
    await bot.get_me()
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_multipart_form_retry_after_connect_error():
    from aiogram.methods import SendDocument
    from aiogram.types import BufferedInputFile

    ok = '{"ok": true, "result": {"message_id": 1, "date": 0, "chat": {"id": 1, "type": "private"}}}'
    bot, fake = _make([aiohttp.ConnectionTimeoutError(), None])
    orig = FakeResponse.text

    async def text(self):
        return ok

    FakeResponse.text = text
    try:
        msg = await bot(SendDocument(chat_id=1, document=BufferedInputFile(b"x", filename="a.pdf")))
    finally:
        FakeResponse.text = orig
    assert msg.message_id == 1
    assert len(fake.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [asyncio.TimeoutError(), aiohttp.ServerDisconnectedError()])
async def test_other_errors_not_retried(exc):
    bot, fake = _make([exc, None])
    with pytest.raises(TelegramNetworkError):
        await bot.get_me()
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_client_timeout_default_and_explicit():
    bot, fake = _make([None])
    await bot.get_me()
    t = fake.calls[0]
    assert isinstance(t, aiohttp.ClientTimeout)
    assert t.sock_connect == 4.0
    assert t.total == 60

    bot, fake = _make([None])
    from aiogram.methods import GetMe
    await bot(GetMe(), request_timeout=70)
    assert fake.calls[0].total == 70
    assert fake.calls[0].sock_connect == 4.0


@pytest.mark.asyncio
async def test_wait_for_telegram_retries_then_caches(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(telegram_session.asyncio, "sleep", no_sleep)
    # каждый get_me: 3 провала подключения подряд = 1 TelegramNetworkError
    bot, fake = _make([aiohttp.ConnectionTimeoutError()] * 6 + [None])
    await wait_for_telegram(bot, attempts=3, delay=0)
    assert len(fake.calls) == 7
    await bot.me()
    assert len(fake.calls) == 7  # из кэша


@pytest.mark.asyncio
async def test_wait_for_telegram_exhausted_raises(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(telegram_session.asyncio, "sleep", no_sleep)
    bot, fake = _make([aiohttp.ConnectionTimeoutError()] * 6)
    with pytest.raises(TelegramNetworkError):
        await wait_for_telegram(bot, attempts=2, delay=0)
    assert len(fake.calls) == 6


def test_aiogram_version_canary():
    assert aiogram.__version__ == "3.13.1", (
        "пересмотреть make_request в telegram_session при обновлении aiogram"
    )
