"""
VOXScript 로컬 백엔드 → 중앙 인증 서버(Railway) 호출 클라이언트
"""

import os
import httpx
from fastapi import HTTPException

CENTRAL_API_URL = os.getenv("VOXSCRIPT_CENTRAL_API", "https://web-production-00a61.up.railway.app")

async def login(username: str, password: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{CENTRAL_API_URL}/login",
            json={"username": username, "password": password},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=resp.json().get("detail", "로그인 실패"),
        )
    return resp.json()


async def check_usage(authorization: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{CENTRAL_API_URL}/usage/status",
            headers={"Authorization": authorization},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=resp.json().get("detail", "인증 실패"),
        )
    if not resp.json()["allowed"]:
        raise HTTPException(status_code=429, detail="이번 달 사용 한도를 초과했습니다.")


async def record_usage(authorization: str, seconds: int) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{CENTRAL_API_URL}/usage/record",
            headers={"Authorization": authorization},
            json={"seconds": seconds},
        )


async def get_me(authorization: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{CENTRAL_API_URL}/me",
            headers={"Authorization": authorization},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code, detail=resp.json().get("detail", "인증 실패")
        )
    return resp.json()


async def list_accounts(authorization: str) -> list:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{CENTRAL_API_URL}/admin/accounts",
            headers={"Authorization": authorization},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code, detail=resp.json().get("detail", "조회 실패")
        )
    return resp.json()


async def create_account(authorization: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{CENTRAL_API_URL}/admin/accounts",
            headers={"Authorization": authorization},
            json=payload,
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=resp.status_code, detail=resp.json().get("detail", "생성 실패")
        )
    return resp.json()


async def update_account(authorization: str, account_id: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{CENTRAL_API_URL}/admin/accounts/{account_id}",
            headers={"Authorization": authorization},
            json=payload,
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code, detail=resp.json().get("detail", "수정 실패")
        )
    return resp.json()
