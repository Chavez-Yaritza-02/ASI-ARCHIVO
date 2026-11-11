"""Bitácora de auditoría: quién hizo qué y cuándo.

La aplicación solo inserta registros aquí; nunca los modifica ni los borra.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, FechaHora, JSONFlexible


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(FechaHora(), server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    accion: Mapped[str] = mapped_column(String(40))  # p. ej. "login", "crear", "editar"
    entidad: Mapped[str | None] = mapped_column(String(60))
    entidad_id: Mapped[str | None] = mapped_column(String(40))
    antes: Mapped[dict[str, Any] | None] = mapped_column(JSONFlexible)
    despues: Mapped[dict[str, Any] | None] = mapped_column(JSONFlexible)
    ip: Mapped[str | None] = mapped_column(String(45))
