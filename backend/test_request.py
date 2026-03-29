import httpx
import os
import sys

sys.path.insert(0, os.getcwd())
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.user import User

async def main():
    async with AsyncSessionLocal() as db:
        user = User(username='test_support', hashed_password='123')
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        from app.utils.security import create_access_token
        token = create_access_token({'sub': user.id})
        
        import httpx
        res = httpx.post('http://127.0.0.1:8000/support/create', json={'subject': 'test', 'message': 'test', 'contact': 'test', 'reference': 'test'}, headers={'Authorization': f'Bearer {token}'})
        print(res.status_code)
        print(res.text)

asyncio.run(main())
