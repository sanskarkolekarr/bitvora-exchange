import asyncio
from sqlalchemy import text
from app.core.database import engine

async def main():
    async with engine.begin() as conn:
        await conn.execute(text('ALTER TABLE transactions ADD COLUMN IF NOT EXISTS telegram_sent BOOLEAN DEFAULT false NOT NULL;'))
    print("Database updated successfully.")

if __name__ == "__main__":
    asyncio.run(main())
