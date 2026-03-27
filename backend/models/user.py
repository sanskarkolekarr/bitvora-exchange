"""
BITVORA EXCHANGE — Pydantic Models: User
"""

from pydantic import BaseModel, Field, field_validator
import re


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)
    password: str = Field(..., min_length=8)
    default_upi: str = Field(..., min_length=4)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]{3,20}$", v):
            raise ValueError(
                "Username must be 3-20 characters, letters, numbers, and underscores only"
            )
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class MessageResponse(BaseModel):
    message: str


class UserProfile(BaseModel):
    username: str
    created_at: str
    total_transactions: int = 0
    total_inr_received: float = 0.0
    default_upi: str | None = None
    is_banned: bool = False
