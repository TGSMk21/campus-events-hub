"""PostgreSQL access: one shared connection pool and an explicit transaction helper.

Every query in the codebase goes through psycopg with %s placeholders, so user
input is always sent as a bound parameter and never concatenated into SQL
(Lab 6, A03 Injection).
"""
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = ConnectionPool(
            conninfo=s.DATABASE_URL,
            min_size=s.DB_POOL_MIN,
            max_size=s.DB_POOL_MAX,
            timeout=s.DB_POOL_TIMEOUT,
            max_idle=s.DB_POOL_MAX_IDLE,
            kwargs={"row_factory": dict_row, "autocommit": True},
            name="hub",
            open=False,
        )
        _pool.open(wait=True)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def pool() -> ConnectionPool:
    return init_pool()


def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple | dict = ()) -> int:
    with pool().connection() as conn:
        return conn.execute(sql, params).rowcount


@contextmanager
def transaction(isolation: str = "READ COMMITTED") -> Iterator[psycopg.Connection]:
    """Explicit BEGIN / COMMIT / ROLLBACK (Lab 7, Task 2).

    Connections in the pool run in autocommit mode, so the transaction boundary
    is written out by hand here. Any exception inside the block rolls back every
    statement issued on this connection, then re-raises.
    """
    if isolation not in {"READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"}:
        raise ValueError("bad isolation level")
    with pool().connection() as conn:
        conn.execute(f"BEGIN ISOLATION LEVEL {isolation}")   # constant from the allow-list above
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
