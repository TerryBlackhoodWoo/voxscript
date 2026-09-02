# backend/services/auth_service.py
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException

from config import (
    VOX_JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_LOCKOUT_MINUTES,
)
from DAO import account_vox_dao


async def login(username: str, password: str) -> str:
    account = await account_vox_dao.find_by_username(username)

    if not account:
        raise HTTPException(
            status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다."
        )

    if account["locked_until"] and account["locked_until"] > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=423,
            detail="로그인 시도 초과로 계정이 잠겼습니다. 잠시 후 다시 시도해주세요.",
        )

    if not account["is_active"]:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    if not bcrypt.checkpw(password.encode(), account["password_hash"].encode()):
        new_attempts = account["failed_login_attempts"] + 1
        lock_until = None
        if new_attempts >= LOGIN_MAX_ATTEMPTS:
            lock_until = datetime.now(timezone.utc) + timedelta(
                minutes=LOGIN_LOCKOUT_MINUTES
            )
        await account_vox_dao.register_failed_login(account["id"], lock_until)
        raise HTTPException(
            status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다."
        )

    await account_vox_dao.reset_login_attempts(account["id"])

    payload = {
        "sub": str(account["id"]),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, VOX_JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_account(authorization: str = Header(...)) -> dict:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="인증 토큰이 필요합니다.")

    try:
        payload = jwt.decode(token, VOX_JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401, detail="토큰이 만료되었거나 유효하지 않습니다."
        )

    account = await account_vox_dao.find_by_id(payload["sub"])
    if not account or not account["is_active"]:
        raise HTTPException(status_code=401, detail="유효하지 않은 계정입니다.")

    return account
