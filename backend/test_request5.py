import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.getcwd())
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.utils.security import create_access_token
import httpx

async def get_token():
    async with AsyncSessionLocal() as db:
        user = User(username='test_support_' + str(uuid.uuid4())[:8], hashed_password='123')
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token({'sub': user.id})

async def main():
    token = await get_token()
    res = httpx.post('http://127.0.0.1:8000/support/create', json={'subject': 'test subject', 'message': 'test message', 'contact': 'test contact', 'reference': 'test reference'}, headers={'Authorization': f'Bearer {token}'})
    print(f"Status: {res.status_code}")
    print(res.text)

asyncio.run(main())
