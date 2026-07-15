"""
auth.py
-------
API key authentication dependency for FastAPI.
Clients must pass 'X-API-Key: <key>' header on every request.
"""

from __future__ import annotations
from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    settings = get_settings()
    if api_key not in settings.get_api_key_list():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Pass it as 'X-API-Key' header.",
        )
    return api_key
