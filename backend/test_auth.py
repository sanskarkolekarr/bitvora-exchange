import asyncio
import httpx

async def test():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        print("Registering...")
        res = await client.post("/auth/register", json={
            "username": "TestUser123",
            "password": "Password123!",
            "default_upi": "test@upi"
        })
        print(res.status_code, res.text)
        
        print("Logging in...")
        res2 = await client.post("/auth/login", json={
            "username": "TestUser123",
            "password": "Password123!"
        })
        print(res2.status_code, res2.text)

asyncio.run(test())
