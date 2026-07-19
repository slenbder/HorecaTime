"""Тесты Фазы 2c: pending_approvals вместо callback_data + защита от двойного апрува."""
import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import (
    create_migration_tables,
    create_pending_approval,
    get_pending_approval,
    resolve_pending_approval,
    reopen_pending_approval,
    get_shift,
)


@pytest.fixture()
def approvals_db(tmp_path):
    path = str(tmp_path / "approvals_test.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


def _make_callback(data: str, caller_id: int = 999, message_text: str = "Отчёт") -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.message.text = message_text
    cb.from_user.id = caller_id
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.bot.send_message = AsyncMock()
    return cb


# ---------------------------------------------------------------------------
# CRUD: атомарный resolve-guard
# ---------------------------------------------------------------------------

class TestPendingApprovalCrud:

    @pytest.mark.asyncio
    async def test_create_and_get(self, approvals_db):
        approval_id = await create_pending_approval(
            approvals_db, 12345, "ah_photos", "2026-07-03", 10.0, 3
        )

        approval = await get_pending_approval(approvals_db, approval_id)
        assert approval["telegram_id"] == 12345
        assert approval["approval_type"] == "ah_photos"
        assert approval["shift_date"] == "2026-07-03"
        assert approval["hours"] == 10.0
        assert approval["photo_count"] == 3
        assert approval["resolved_at"] is None

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, approvals_db):
        assert await get_pending_approval(approvals_db, 777) is None

    @pytest.mark.asyncio
    async def test_second_resolve_returns_false(self, approvals_db):
        approval_id = await create_pending_approval(
            approvals_db, 12345, "loyalty", "2026-07-03", 8.0, 2
        )

        assert await resolve_pending_approval(approvals_db, approval_id, 999) is True
        assert await resolve_pending_approval(approvals_db, approval_id, 888) is False

        approval = await get_pending_approval(approvals_db, approval_id)
        assert approval["resolved_by"] == 999   # второй админ не перезаписал

    @pytest.mark.asyncio
    async def test_concurrent_resolves_exactly_one_true(self, approvals_db):
        """Гонка двух админов: ровно один resolve проходит."""
        approval_id = await create_pending_approval(
            approvals_db, 12345, "filling", "2026-07-03", 8.0, 3
        )

        results = await asyncio.gather(*[
            resolve_pending_approval(approvals_db, approval_id, admin)
            for admin in (901, 902, 903, 904, 905)
        ])

        assert sum(results) == 1

    @pytest.mark.asyncio
    async def test_reopen_allows_resolve_again(self, approvals_db):
        approval_id = await create_pending_approval(
            approvals_db, 12345, "ah_photos", "2026-07-03", 10.0, 3
        )
        await resolve_pending_approval(approvals_db, approval_id, 999)

        await reopen_pending_approval(approvals_db, approval_id)

        assert await resolve_pending_approval(approvals_db, approval_id, 999) is True


# ---------------------------------------------------------------------------
# Двойное нажатие «Одобрить»
# ---------------------------------------------------------------------------

class TestDoubleApprove:

    @pytest.mark.asyncio
    async def test_second_click_answers_without_edit(self, approvals_db):
        """Второй клик → 'Заявка уже обработана', без edit_text (фикс 'message is not modified'),
        смена в shifts не задублирована."""
        from app.bot.handlers.auth import process_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "ah_photos", "2026-07-03", 10.0, 3
        )
        cb1 = _make_callback(f"apprv:{approval_id}:2")
        cb2 = _make_callback(f"apprv:{approval_id}:3")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_shift.return_value = ""
            await process_approval_callback(cb1)
            await process_approval_callback(cb2)

        cb1.message.edit_text.assert_called_once()
        cb2.message.edit_text.assert_not_called()
        cb2.answer.assert_called_with("Заявка уже обработана")

        # Смена записана один раз — решением первого админа (2 фото → AH=1.0)
        rec = await get_shift(approvals_db, 12345, "2026-07-03")
        assert (rec["hours"], rec["extra_hours"]) == (10.0, 1.0)
        mock_sc.write_shift.assert_called_once()


# ---------------------------------------------------------------------------
# Полный флоу: отчёт официанта → заявка в БД → апрув → смена записана
# ---------------------------------------------------------------------------

class TestFullApprovalFlow:

    @pytest.mark.asyncio
    async def test_report_creates_approval_then_approve_writes_shift(self, approvals_db):
        from app.bot.handlers.userhours import _send_waiter_report
        from app.bot.handlers.auth import process_approval_callback

        message = MagicMock()
        message.from_user.id = 12345
        message.from_user.username = "waiter"
        message.answer = AsyncMock()
        message.bot.send_message = AsyncMock()
        message.bot.send_media_group = AsyncMock()
        state = AsyncMock()
        result = {"day": 3, "month": 7, "year": 2026, "h": 10.0, "start": 10.0, "end": 20.0}

        with (
            patch("app.bot.handlers.userhours.DB_PATH", approvals_db),
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Официант"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[111])),
        ):
            await _send_waiter_report(message, state, 12345, result, ["p1", "p2", "p3"])

        # Заявка в БД, в callback_data — только id и решение
        keyboard = message.bot.send_message.call_args.kwargs["reply_markup"]
        callback_datas = [b.callback_data for b in keyboard.inline_keyboard[0]]
        assert callback_datas == [f"apprv:1:{i}" for i in range(4)]

        approval = await get_pending_approval(approvals_db, 1)
        assert approval["approval_type"] == "ah_photos"
        assert approval["hours"] == 10.0
        assert approval["photo_count"] == 3

        # Админ жмёт «2»
        cb = _make_callback("apprv:1:2")
        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_shift.return_value = ""
            await process_approval_callback(cb)

        approval = await get_pending_approval(approvals_db, 1)
        assert approval["resolved_at"] is not None
        assert approval["resolved_by"] == 999

        rec = await get_shift(approvals_db, 12345, "2026-07-03")
        assert (rec["hours"], rec["extra_hours"], rec["source"]) == (10.0, 1.0, "admin_approve")
        cb.bot.send_message.assert_called()   # официант уведомлён

    @pytest.mark.asyncio
    async def test_report_db_failure_no_admin_report(self, approvals_db):
        """Ошибка создания заявки → отчёт админам НЕ отправлен, официанту ❌."""
        from app.bot.handlers.userhours import _send_waiter_report

        message = MagicMock()
        message.from_user.id = 12345
        message.from_user.username = "waiter"
        message.answer = AsyncMock()
        message.bot.send_message = AsyncMock()
        message.bot.send_media_group = AsyncMock()
        state = AsyncMock()
        result = {"day": 3, "month": 7, "year": 2026, "h": 10.0, "start": 10.0, "end": 20.0}

        with (
            patch("app.bot.handlers.userhours.create_pending_approval",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Официант"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[111])),
        ):
            await _send_waiter_report(message, state, 12345, result, ["p1"])

        message.bot.send_message.assert_not_called()
        state.clear.assert_not_called()
        assert "❌ Ошибка" in str(message.answer.call_args)

    @pytest.mark.asyncio
    async def test_filling_approve_increments_and_mirrors_total(self, approvals_db):
        from app.bot.handlers.auth import process_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "filling", "2026-07-20", 8.0, 3
        )
        cb = _make_callback(f"apprv:{approval_id}:3")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_check_filling_to_phantom.return_value = True
            mock_sc.get_phantom_checks_summary.return_value = 3
            await process_approval_callback(cb)

        with sqlite3.connect(approvals_db) as conn:
            total = conn.execute(
                "SELECT count FROM check_filling WHERE fill_date = '2026-07-20'"
            ).fetchone()[0]
        assert total == 3
        mock_sc.write_check_filling_to_phantom.assert_called_once_with("20.07.26", 3, total=3)
        mock_sc.get_phantom_checks_summary.assert_called_once_with("second")

    @pytest.mark.asyncio
    async def test_filling_summary_read_failure_still_succeeds(self, approvals_db):
        """get_phantom_checks_summary падает после успешного коммита →
        операция всё равно завершается успешно: админ получает сообщение
        с плейсхолдером сводки, официант получает своё уведомление."""
        from app.bot.handlers.auth import process_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "filling", "2026-07-20", 8.0, 3
        )
        cb = _make_callback(f"apprv:{approval_id}:3")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_check_filling_to_phantom.return_value = True
            mock_sc.get_phantom_checks_summary.side_effect = Exception("Sheets down")
            await process_approval_callback(cb)

        # Данные всё равно закоммичены — падение сводки не должно их откатывать
        with sqlite3.connect(approvals_db) as conn:
            total = conn.execute(
                "SELECT count FROM check_filling WHERE fill_date = '2026-07-20'"
            ).fetchone()[0]
        assert total == 3
        approval = await get_pending_approval(approvals_db, approval_id)
        assert approval["resolved_at"] is not None

        # Админ получил сообщение с плейсхолдером вместо генерик-ошибки
        admin_text = cb.message.answer.call_args[0][0]
        assert "сводка пула временно недоступна" in admin_text
        assert "✅ Наполняемость записана" in admin_text

        # Официант получил своё уведомление как обычно
        cb.bot.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

class TestRejectApproval:

    @pytest.mark.asyncio
    async def test_reject_resolves_without_writing(self, approvals_db):
        from app.bot.handlers.auth import process_reject_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "filling", "2026-07-20", 8.0, 3
        )
        cb = _make_callback(f"rejct:{approval_id}")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            await process_reject_approval_callback(cb)

        approval = await get_pending_approval(approvals_db, approval_id)
        assert approval["resolved_at"] is not None

        with sqlite3.connect(approvals_db) as conn:
            checks = conn.execute("SELECT COUNT(*) FROM check_filling").fetchone()[0]
            shifts = conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0]
        assert (checks, shifts) == (0, 0)   # ничего не записано
        mock_sc.write_check_filling_to_phantom.assert_not_called()
        assert "❌ Отклонено" in str(cb.message.edit_text.call_args)

    @pytest.mark.asyncio
    async def test_reject_double_click_answers_without_edit(self, approvals_db):
        from app.bot.handlers.auth import process_reject_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "filling", "2026-07-20", 8.0, 3
        )
        cb1 = _make_callback(f"rejct:{approval_id}")
        cb2 = _make_callback(f"rejct:{approval_id}")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client"),
        ):
            await process_reject_approval_callback(cb1)
            await process_reject_approval_callback(cb2)

        cb1.message.edit_text.assert_called_once()
        cb2.message.edit_text.assert_not_called()
        cb2.answer.assert_called_with("Заявка уже обработана")


# ---------------------------------------------------------------------------
# Guard'ы единого обработчика и legacy-формат
# ---------------------------------------------------------------------------

class TestApprovalGuards:

    @pytest.mark.asyncio
    async def test_no_rights_does_not_resolve(self, approvals_db):
        from app.bot.handlers.auth import process_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "loyalty", "2026-07-03", 8.0, 2
        )
        cb = _make_callback(f"apprv:{approval_id}:1", caller_id=555)  # не админ

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.SUPERADMIN_IDS", [999]),
            patch("app.bot.handlers.auth.DEVELOPER_ID", 999),
            patch("app.bot.handlers.auth.sheets_client"),
        ):
            await process_approval_callback(cb)

        cb.answer.assert_called_with("❌ Нет прав.", show_alert=True)
        approval = await get_pending_approval(approvals_db, approval_id)
        assert approval["resolved_at"] is None   # заявка не съедена

    @pytest.mark.asyncio
    async def test_n_exceeds_photo_count_rejected_without_resolve(self, approvals_db):
        from app.bot.handlers.auth import process_approval_callback

        approval_id = await create_pending_approval(
            approvals_db, 12345, "loyalty", "2026-07-03", 8.0, 2
        )
        cb = _make_callback(f"apprv:{approval_id}:99")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.sheets_client"),
        ):
            await process_approval_callback(cb)

        cb.answer.assert_called_with("❌ Недопустимое значение.", show_alert=True)
        approval = await get_pending_approval(approvals_db, approval_id)
        assert approval["resolved_at"] is None

    @pytest.mark.asyncio
    async def test_legacy_ah_callback_still_works(self, approvals_db):
        """Старый формат approve_ah:{tg}:{дата}:{h}:{N}:{n} обрабатывается на переходный период."""
        from app.bot.handlers.auth import approve_ah_callback

        cb = _make_callback("approve_ah:12345:03.07.26:10.0:3:2", message_text="Фотоотчёт")

        with (
            patch("app.bot.handlers.auth.DB_PATH", approvals_db),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_shift.return_value = ""
            await approve_ah_callback(cb)

        rec = await get_shift(approvals_db, 12345, "2026-07-03")
        assert (rec["hours"], rec["extra_hours"], rec["source"]) == (10.0, 1.0, "admin_approve")
        cb.message.edit_text.assert_called_once()
