import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from app.core.database import engine, Base
from app.models.ticket import SupportTicket
from sqlalchemy import text

async def main():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'support_tickets');"))
        print(f"Table exists: {res.scalar()}")

asyncio.run(main())
