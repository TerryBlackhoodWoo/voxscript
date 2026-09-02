# backend/DAO/usage_vox_dao.py
from fastapi import HTTPException
from database_pg import get_pool


async def check_and_add_cost(
    account_id: str, cost: float, monthly_limit: float
) -> float:
    """트랜잭션 안에서 누적 + 한도 체크. 초과 시 롤백되고 429."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO usage_counters_vox (account_id, usage_month, estimated_cost)
                VALUES ($1, date_trunc('month', CURRENT_DATE)::date, $2)
                ON CONFLICT (account_id, usage_month)
                DO UPDATE SET estimated_cost = usage_counters_vox.estimated_cost + $2
                RETURNING estimated_cost
                """,
                account_id,
                cost,
            )
            if row["estimated_cost"] > monthly_limit:
                raise HTTPException(429, "이번 달 사용 한도를 초과했습니다.")
            return row["estimated_cost"]


async def get_current_month_usage(account_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT * FROM usage_counters_vox
        WHERE account_id = $1 AND usage_month = date_trunc('month', CURRENT_DATE)::date
        """,
        account_id,
    )
    return dict(row) if row else None


async def get_current_month_stt_seconds(account_id: str) -> int:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT stt_seconds FROM usage_counters_vox
        WHERE account_id = $1 AND usage_month = date_trunc('month', CURRENT_DATE)::date
        """,
        account_id,
    )
    return row["stt_seconds"] if row else 0


async def add_stt_seconds(account_id: str, seconds: int) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO usage_counters_vox (account_id, usage_month, stt_seconds)
        VALUES ($1, date_trunc('month', CURRENT_DATE)::date, $2)
        ON CONFLICT (account_id, usage_month)
        DO UPDATE SET stt_seconds = usage_counters_vox.stt_seconds + $2
        """,
        account_id,
        seconds,
    )
