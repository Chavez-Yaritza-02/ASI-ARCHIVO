"""Configuración administrativa de asistencia."""

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ConfiguracionAsistencia(Base):
    __tablename__ = "configuracion_asistencia"
    __table_args__ = (
        CheckConstraint("id = 1", name="unica"),
        CheckConstraint("tolerancia_minutos BETWEEN 0 AND 120", name="tolerancia"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tolerancia_minutos: Mapped[int] = mapped_column(Integer)
