from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass
class UiLock:
    lock_name: str
    owner_pipeline: str
    owner_task_id: str
    acquire_time: datetime
    heartbeat_time: datetime
    expire_time: datetime
    lease_seconds: int


class InMemoryUiLockRepo:
    def __init__(self) -> None:
        self._locks: dict[str, UiLock] = {}
        self.stale_lock_recovered_count = 0

    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        existing = self._locks.get(lock_name)
        if existing is not None and existing.expire_time > now:
            return False

        self._locks[lock_name] = UiLock(
            lock_name=lock_name,
            owner_pipeline=owner_pipeline,
            owner_task_id=owner_task_id,
            acquire_time=now,
            heartbeat_time=now,
            expire_time=now + timedelta(seconds=lease_seconds),
            lease_seconds=lease_seconds,
        )
        return True

    def heartbeat(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
    ) -> bool:
        lock = self._locks.get(lock_name)
        if lock is None:
            return False
        if lock.owner_pipeline != owner_pipeline or lock.owner_task_id != owner_task_id:
            return False
        lock.heartbeat_time = now
        lock.expire_time = now + timedelta(seconds=lock.lease_seconds)
        return True

    def release(self, lock_name: str, owner_pipeline: str, owner_task_id: str) -> bool:
        lock = self._locks.get(lock_name)
        if lock is None:
            return False
        if lock.owner_pipeline != owner_pipeline or lock.owner_task_id != owner_task_id:
            return False
        del self._locks[lock_name]
        return True

    def recover_stale(
        self,
        lock_name: str,
        recovered_by: str,
        now: datetime,
        stale_after_seconds: int,
    ) -> bool:
        lock = self._locks.get(lock_name)
        if lock is None:
            return False
        stale_at = lock.heartbeat_time + timedelta(seconds=stale_after_seconds)
        if stale_at > now:
            return False
        del self._locks[lock_name]
        self.stale_lock_recovered_count += 1
        return True

    def current_owner(self, lock_name: str) -> str | None:
        lock = self._locks.get(lock_name)
        return None if lock is None else lock.owner_pipeline


class MysqlUiLockRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        expire_time = now + timedelta(seconds=lease_seconds)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM wechat_ui_lock
                    WHERE lock_name = :lock_name
                      AND expire_time <= :now
                    """
                ),
                {"lock_name": lock_name, "now": now},
            )
            result = connection.execute(
                text(
                    """
                    INSERT IGNORE INTO wechat_ui_lock (
                        lock_name,
                        owner_pipeline,
                        owner_task_id,
                        acquire_time,
                        heartbeat_time,
                        expire_time,
                        lease_seconds
                    ) VALUES (
                        :lock_name,
                        :owner_pipeline,
                        :owner_task_id,
                        :acquire_time,
                        :heartbeat_time,
                        :expire_time,
                        :lease_seconds
                    )
                    """
                ),
                {
                    "lock_name": lock_name,
                    "owner_pipeline": owner_pipeline,
                    "owner_task_id": owner_task_id,
                    "acquire_time": now,
                    "heartbeat_time": now,
                    "expire_time": expire_time,
                    "lease_seconds": lease_seconds,
                },
            )
            return int(result.rowcount or 0) == 1

    def heartbeat(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
    ) -> bool:
        statement = text(
            """
            UPDATE wechat_ui_lock
            SET heartbeat_time = :now,
                expire_time = DATE_ADD(:now, INTERVAL lease_seconds SECOND)
            WHERE lock_name = :lock_name
              AND owner_pipeline = :owner_pipeline
              AND owner_task_id = :owner_task_id
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {
                    "lock_name": lock_name,
                    "owner_pipeline": owner_pipeline,
                    "owner_task_id": owner_task_id,
                    "now": now,
                },
            )
            return int(result.rowcount or 0) == 1

    def release(self, lock_name: str, owner_pipeline: str, owner_task_id: str) -> bool:
        statement = text(
            """
            DELETE FROM wechat_ui_lock
            WHERE lock_name = :lock_name
              AND owner_pipeline = :owner_pipeline
              AND owner_task_id = :owner_task_id
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {
                    "lock_name": lock_name,
                    "owner_pipeline": owner_pipeline,
                    "owner_task_id": owner_task_id,
                },
            )
            return int(result.rowcount or 0) == 1
