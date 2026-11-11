"""Calendario institucional, asistencia docente e incidencias.

La lista de docentes esperados en un día NO se guarda: se calcula con los horarios
vigentes en esa fecha. Aquí solo se guardan los registros reales. Un docente sin
registro está "pendiente"; el sistema nunca genera faltas por su cuenta.
"""

from datetime import date, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ConFechas
from app.models.catalogos import Docente

_TURNOS = "('matutino', 'vespertino')"


class EventoCalendario(ConFechas, Base):
    """Días inhábiles, vacaciones, suspensiones y excepciones (días hábiles autorizados)."""

    __tablename__ = "calendario_evento"
    __table_args__ = (
        CheckConstraint("tipo IN ('inhabil', 'vacaciones', 'suspension', 'habil')", name="tipo"),
        CheckConstraint("fecha_fin >= fecha_inicio", name="fechas"),
        CheckConstraint(f"turno IS NULL OR turno IN {_TURNOS}", name="turno"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20))
    fecha_inicio: Mapped[date] = mapped_column(Date, index=True)
    fecha_fin: Mapped[date] = mapped_column(Date, index=True)
    turno: Mapped[str | None] = mapped_column(String(12))  # vacío = todo el día
    descripcion: Mapped[str] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)  # se anula, no se borra
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))


class Asistencia(ConFechas, Base):
    """Registro real de un docente en un día y turno (asistencia general, no por clase)."""

    __tablename__ = "asistencia"
    __table_args__ = (
        UniqueConstraint("docente_id", "fecha", "turno", name="uq_asistencia_docente_dia"),
        CheckConstraint("estado IN ('asistio', 'retardo', 'falto', 'justificado')", name="estado"),
        CheckConstraint(f"turno IN {_TURNOS}", name="turno"),
        CheckConstraint(
            "hora_salida IS NULL OR hora_entrada IS NULL OR hora_salida > hora_entrada",
            name="horas",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    docente_id: Mapped[int] = mapped_column(ForeignKey("docente.id"), index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    turno: Mapped[str] = mapped_column(String(12))
    estado: Mapped[str] = mapped_column(String(15))
    hora_entrada: Mapped[time | None] = mapped_column(Time)
    hora_salida: Mapped[time | None] = mapped_column(Time)
    observaciones: Mapped[str] = mapped_column(Text, default="")
    justificacion: Mapped[str] = mapped_column(Text, default="")
    # Lo programado en ese momento (copia): el registro conserva su sentido aunque el
    # horario cambie después.
    horario_id: Mapped[int | None] = mapped_column(ForeignKey("horario.id"))
    programado_inicio: Mapped[time | None] = mapped_column(Time)
    programado_fin: Mapped[time | None] = mapped_column(Time)
    # Registrado en un día inhábil por excepción autorizada.
    en_dia_inhabil: Mapped[bool] = mapped_column(Boolean, default=False)
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    correcciones: Mapped[int] = mapped_column(Integer, default=0)

    docente: Mapped[Docente] = relationship(lazy="joined")


class Incidencia(ConFechas, Base):
    """Nota manual de la bitácora: comisión, permiso, salida anticipada, cambio de aula…"""

    __tablename__ = "incidencia"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('comision', 'permiso', 'salida_anticipada', 'cambio_aula', 'otra')",
            name="tipo",
        ),
        CheckConstraint(f"turno IS NULL OR turno IN {_TURNOS}", name="turno"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    docente_id: Mapped[int | None] = mapped_column(ForeignKey("docente.id"))
    turno: Mapped[str | None] = mapped_column(String(12))
    tipo: Mapped[str] = mapped_column(String(20))
    descripcion: Mapped[str] = mapped_column(Text)
    anulada: Mapped[bool] = mapped_column(Boolean, default=False)
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))

    docente: Mapped[Docente | None] = relationship(lazy="joined")
