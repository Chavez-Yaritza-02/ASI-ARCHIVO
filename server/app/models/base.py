"""Clase base de todos los modelos y tipos portables entre PostgreSQL y SQLite."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# Nombres predecibles para índices y restricciones: facilita las migraciones.
_CONVENCION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB en PostgreSQL (servidor central); JSON (texto) en SQLite (modo local).
JSONFlexible = JSON().with_variant(JSONB(), "postgresql")


class FechaHora(TypeDecorator):
    """Fecha y hora con zona horaria en ambos motores.

    PostgreSQL guarda la zona por sí mismo. SQLite no la conoce: ahí se guarda siempre
    en UTC sin zona y se devuelve como UTC con zona, para que las comparaciones con
    `datetime.now(UTC)` funcionen igual que en el servidor central.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialect: Any) -> datetime | None:
        if valor is None or dialect.name != "sqlite":
            return valor
        if valor.tzinfo is not None:
            valor = valor.astimezone(UTC)
        return valor.replace(tzinfo=None)

    def process_result_value(self, valor: datetime | None, dialect: Any) -> datetime | None:
        if valor is None or dialect.name != "sqlite":
            return valor
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_CONVENCION)


class ConFechas:
    """Agrega fechas de creación y última modificación."""

    creado_en: Mapped[datetime] = mapped_column(FechaHora(), server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        FechaHora(), server_default=func.now(), onupdate=func.now()
    )
