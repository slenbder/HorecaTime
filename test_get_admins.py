import asyncio
from app.db.models import get_admins_by_department

async def test():
    admins = await get_admins_by_department("data/bot.db", "Кухня")
    print(f"Админы кухни: {admins}")

asyncio.run(test())
