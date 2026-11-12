"""Periodos académicos y horarios versionados.

Un horario pertenece a un docente y a un periodo. Cada cambio importante crea una
nueva versión en lugar de modificar la anterior:

    borrador --(confirmar)--> vigente --(otra versión confirmada)--> historico
    borrador --(descartar)--> descartado

Solo los borradores se editan. La base de datos garantiza que haya como máximo
un periodo activo y una versión vigente por docente y periodo.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.tipos import FechaHora
from app.models.base import Base, ConFechas
from app.models.catalogos import Asignatura, Aula, Docente, Grupo


class Periodo(ConFechas, Base):
    __tablename__ = "periodo"
    __table_args__ = (
        CheckConstraint("fecha_fin > fecha_inicio", name="fechas"),
        CheckConstraint("estado IN ('borrador', 'activo', 'cerrado')", name="estado"),
        # Solo un periodo activo a la vez.
        Index(
            "uq_periodo_un_activo",
            "estado",
            unique=True,
            postgresql_where=text("estado = 'activo'"),
            sqlite_where=text("estado = 'activo'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)  # "AGOSTO - DICIEMBRE 2026"
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="borrador")


class Horario(ConFechas, Base):
    """Una versión del horario de un docente en un periodo."""

    __tablename__ = "horario"
    __table_args__ = (
        UniqueConstraint("docente_id", "periodo_id", "version", name="uq_horario_version"),
        CheckConstraint(
            "estado IN ('borrador', 'vigente', 'historico', 'descartado')", name="estado"
        ),
        CheckConstraint("origen IN ('manual', 'pdf', 'excel', 'csv')", name="origen"),
        CheckConstraint(
            "(vigente_hasta IS NULL OR (vigente_desde IS NOT NULL "
            "AND vigente_hasta >= vigente_desde)) "
            "AND (NOT vigencia_confirmada OR vigente_desde IS NOT NULL)",
            name="vigencia_fechas",
        ),
        # Solo una versión vigente por docente y periodo.
        Index(
            "uq_horario_un_vigente",
            "docente_id",
            "periodo_id",
            unique=True,
            postgresql_where=text("estado = 'vigente'"),
            sqlite_where=text("estado = 'vigente'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    docente_id: Mapped[int] = mapped_column(ForeignKey("docente.id"), index=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("periodo.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(20), default="borrador")
    origen: Mapped[str] = mapped_column(String(10), default="manual")
    # Datos del documento institucional (fecha y versión que trae el PDF), si existe.
    fecha_documento: Mapped[date | None] = mapped_column(Date)
    version_documento: Mapped[int | None] = mapped_column(Integer)
    notas: Mapped[str] = mapped_column(Text, default="")
    basado_en_id: Mapped[int | None] = mapped_column(ForeignKey("horario.id"))
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    confirmado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    confirmado_en: Mapped[datetime | None] = mapped_column(FechaHora())
    # Fechas en que esta versión rige (se fijan al confirmarla y al ser reemplazada).
    # La bitácora usa la versión que regía en cada fecha, no la actual.
    vigente_desde: Mapped[date | None] = mapped_column(Date)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    vigencia_confirmada: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    docente: Mapped[Docente] = relationship(lazy="joined")
    periodo: Mapped[Periodo] = relationship(lazy="joined")
    bloques: Mapped[list["BloqueHorario"]] = relationship(
        back_populates="horario",
        cascade="all, delete-orphan",
        order_by="(BloqueHorario.dia, BloqueHorario.hora_inicio)",
        lazy="selectin",
    )


class BloqueHorario(Base):
    """Una actividad continua en un día: p. ej. lunes 07:00–09:00, CÁLC. DIF., grupo A, M01."""

    __tablename__ = "bloque_horario"
    __table_args__ = (
        CheckConstraint("dia BETWEEN 0 AND 5", name="dia"),  # 0 = lunes … 5 = sábado
        CheckConstraint("hora_fin > hora_inicio", name="horas"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    horario_id: Mapped[int] = mapped_column(
        ForeignKey("horario.id", ondelete="CASCADE"), index=True
    )
    dia: Mapped[int] = mapped_column(Integer)
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time] = mapped_column(Time)
    asignatura_id: Mapped[int] = mapped_column(ForeignKey("asignatura.id"))
    grupo_id: Mapped[int | None] = mapped_column(ForeignKey("grupo.id"))
    # Letra leída del documento cuando aún no se sabe a qué grupo corresponde
    # (pendiente de validación). Se usa solo si grupo_id está vacío.
    grupo_letra: Mapped[str | None] = mapped_column(String(5))
    aula_id: Mapped[int | None] = mapped_column(ForeignKey("aula.id"))

    horario: Mapped[Horario] = relationship(back_populates="bloques")
    asignatura: Mapped[Asignatura] = relationship(lazy="joined")
    grupo: Mapped[Grupo | None] = relationship(lazy="joined")
    aula: Mapped[Aula | None] = relationship(lazy="joined")
