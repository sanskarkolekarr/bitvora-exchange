import asyncio
import asyncpg

async def test_db():
    print("Connecting to Supabase...")
    dsn = "postgresql://postgres.gbaxlqphrxnnuejunnyy:54uC3v6XM1wF7rkd@aws-1-ap-south-1.pooler.supabase.com:5432/postgres?ssl=require"
    try:
        conn = await asyncpg.connect(dsn)
        print("Connected successfully!")
        val = await conn.fetchval("SELECT 1")
        print("Query output:", val)
        await conn.close()
    except Exception as e:
        print("Error connecting:", getattr(e, "message", str(e)))

if __name__ == "__main__":
    asyncio.run(test_db())
