"""Catálogos: docentes, asignaturas (materias y actividades), grupos y aulas.

Ningún registro se borra: se desactiva con `activo = False`, para que los
horarios y asistencias antiguos sigan apuntando a datos válidos.
"""

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ConFechas


class Docente(ConFechas, Base):
    __tablename__ = "docente"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Como aparece en los horarios institucionales: "APELLIDOS NOMBRES".
    nombre: Mapped[str] = mapped_column(String(150))
    # Sin acentos, mayúsculas y espacios simples: evita duplicados y facilita búsquedas.
    nombre_normalizado: Mapped[str] = mapped_column(String(150), unique=True)
    nomina: Mapped[str | None] = mapped_column(String(20), unique=True)
    correo: Mapped[str | None] = mapped_column(String(120))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Asignatura(ConFechas, Base):
    """Materia (clase con grupo) u otra actividad (gestión, tutoría, residencia…)."""

    __tablename__ = "asignatura"
    __table_args__ = (CheckConstraint("tipo IN ('materia', 'actividad')", name="tipo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    nombre_normalizado: Mapped[str] = mapped_column(String(120), unique=True)
    tipo: Mapped[str] = mapped_column(String(20), default="materia")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Grupo(ConFechas, Base):
    __tablename__ = "grupo"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(20), unique=True)  # p. ej. "A", "N"
    descripcion: Mapped[str] = mapped_column(String(200), default="")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Aula(ConFechas, Base):
    __tablename__ = "aula"

    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(30), unique=True)  # p. ej. "M05", "Sala EM"
    descripcion: Mapped[str] = mapped_column(String(200), default="")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
