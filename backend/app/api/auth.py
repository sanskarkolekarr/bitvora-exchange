from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.models.user import User
from app.models.user_payment import UserPayment
from app.utils.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    default_upi: str

class RefreshRequest(BaseModel):
    refresh_token: str


# UPI validation — mirrors the one in api/user.py
import re
_UPI_PATTERN = re.compile(r"^[a-zA-Z0-9.\-_]{2,50}@[a-zA-Z][a-zA-Z0-9]{2,30}$")

def _validate_upi(upi: str) -> str:
    cleaned = upi.strip().lower()
    if not cleaned:
        raise ValueError("UPI ID cannot be empty")
    if len(cleaned) < 5 or len(cleaned) > 80:
        raise ValueError("UPI ID must be between 5 and 80 characters")
    if not _UPI_PATTERN.match(cleaned):
        raise ValueError("Invalid UPI format. Expected: username@provider")
    return cleaned


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    safe_user = req.username.strip().lower()
    result = await db.execute(select(User).filter(User.username.ilike(safe_user)))
    user = result.scalar_one_or_none()
    
    if not user:
        print(f"[AUTH LOGIN] Denied: User '{safe_user}' does not exist.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
        
    if not verify_password(req.password, user.hashed_password):
        print(f"[AUTH LOGIN] Denied: Invalid password provided for '{safe_user}'.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is banned",
        )
        
    access_token = create_access_token(data={"sub": str(user.id), "username": user.username})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    safe_user = req.username.strip().lower()

    # Check if username exists
    res = await db.execute(select(User).filter(User.username.ilike(safe_user)))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    # Validate UPI format
    try:
        validated_upi = _validate_upi(req.default_upi)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    hashed = get_password_hash(req.password)
    new_user = User(
        username=safe_user,
        hashed_password=hashed,
        default_upi=validated_upi,
    )
    db.add(new_user)
    await db.flush()  # get the user.id

    # Create initial payment record (audit trail)
    initial_payment = UserPayment(
        user_id=new_user.id,
        upi_id=validated_upi,
        is_active=True,
    )
    db.add(initial_payment)
    await db.flush()
    
    return {"message": "User created successfully"}

@router.post("/refresh")
async def refresh_token_route(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    # Decrypt token
    from app.utils.security import jwt, SECRET_KEY, ALGORITHM, JWTError
    try:
        payload = jwt.decode(req.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    # User check
    res = await db.execute(select(User).filter(User.id == user_id, User.is_banned == False))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or banned")
        
    # issue new tokens
    access_token = create_access_token(data={"sub": str(user.id), "username": user.username})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }
