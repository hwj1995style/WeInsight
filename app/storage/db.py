from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import MysqlConfig


def create_mysql_engine(config: MysqlConfig) -> Engine:
    url = (
        f"mysql+pymysql://{config.username}:{config.password}"
        f"@{config.host}:{config.port}/{config.database}?charset=utf8mb4"
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)
