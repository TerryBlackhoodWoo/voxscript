import asyncpg
from config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def connect():
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    print("[DB] Postgres pool connected", flush=True)


async def close():
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError(
            "Postgres 풀이 아직 연결되지 않았습니다. connect()를 먼저 호출하세요."
        )
    return _pool
