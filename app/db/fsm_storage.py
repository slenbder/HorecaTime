import json
import logging
from typing import Any, Dict, Optional

import aiosqlite
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

logger = logging.getLogger(__name__)


class SQLiteStorage(BaseStorage):
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_str = state.state if hasattr(state, "state") else state
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO fsm_storage (chat_id, user_id, bot_id, state, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT (chat_id, user_id, bot_id)
                DO UPDATE SET state = excluded.state, updated_at = datetime('now')
            """, (key.chat_id, key.user_id, key.bot_id, state_str))
            await db.commit()
        logger.debug(f"FSM state set: user={key.user_id} → {state_str}")

    async def get_state(self, key: StorageKey) -> Optional[str]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT state FROM fsm_storage "
                "WHERE chat_id=? AND user_id=? AND bot_id=?",
                (key.chat_id, key.user_id, key.bot_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO fsm_storage (chat_id, user_id, bot_id, data, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT (chat_id, user_id, bot_id)
                DO UPDATE SET data = excluded.data, updated_at = datetime('now')
            """, (key.chat_id, key.user_id, key.bot_id, json.dumps(data)))
            await db.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT data FROM fsm_storage "
                "WHERE chat_id=? AND user_id=? AND bot_id=?",
                (key.chat_id, key.user_id, key.bot_id),
            ) as cursor:
                row = await cursor.fetchone()
                return json.loads(row[0]) if (row and row[0]) else {}

    async def close(self) -> None:
        pass
