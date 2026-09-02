# backend/DAO/account_vox_dao.py
from database_pg import get_pool


async def find_by_username(username: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, is_active, password_hash, failed_login_attempts, locked_until, is_admin, monthly_minutes_limit
        FROM accounts_vox
        WHERE username = $1
        """,
        username,
    )
    return dict(row) if row else None


async def find_by_id(account_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, is_active, is_admin, username, monthly_minutes_limit
        FROM accounts_vox
        WHERE id = $1
        """,
        account_id,
    )
    return dict(row) if row else None


async def register_failed_login(account_id: str, lock_until) -> None:
    pool = get_pool()
    await pool.execute(
        """
        UPDATE accounts_vox
        SET failed_login_attempts = failed_login_attempts + 1,
            locked_until = COALESCE($2, locked_until)
        WHERE id = $1
        """,
        account_id,
        lock_until,
    )


async def reset_login_attempts(account_id: str) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE accounts_vox SET failed_login_attempts = 0, locked_until = NULL WHERE id = $1",
        account_id,
    )
