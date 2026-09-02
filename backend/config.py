# backend/config.py
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("환경변수 DATABASE_URL이 설정되지 않았습니다 (.env 확인).")

_vox_jwt_secret = os.getenv("VOX_JWT_SECRET")
if not _vox_jwt_secret:
    raise RuntimeError("환경변수 VOX_JWT_SECRET이 설정되지 않았습니다 (.env 확인).")

VOX_JWT_SECRET: str = _vox_jwt_secret  # ← 여기서 명시적으로 str 타입 확정

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 12
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
