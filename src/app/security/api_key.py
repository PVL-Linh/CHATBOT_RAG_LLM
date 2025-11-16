# app/security/api_key.py
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY_NAME = "X-API-Key"
API_KEY = os.getenv("TIXIMAX_API_KEY", "123456")

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def require_api_key(api_key: str = Depends(api_key_header)):
    if not api_key or api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return api_key
