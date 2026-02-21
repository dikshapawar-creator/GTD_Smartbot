from pydantic import BaseModel, EmailStr, Field, field_validator
from app.core.security import validate_password

class AdminSetupRequest(BaseModel):
    tenant_name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(...)
    setup_token: str

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        if not validate_password(v):
            raise ValueError(
                "Password must be 12+ chars, include upper, lower, number, and special character."
            )
        return v
