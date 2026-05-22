"""SQLAlchemy declarative base with a sane naming convention.

Имя index/uq/fk constraint фиксируется заранее — иначе Alembic autogenerate
ломается на ALTER TABLE: имена ограничений у Postgres начинают вычисляться
неконсистентно между ОС и версиями. Та же конвенция, что и в SQLAlchemy
docs.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Common declarative base used by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
