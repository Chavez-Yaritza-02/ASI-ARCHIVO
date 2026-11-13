"""Zona de revisión de incidencias importadas desde Excel (faltas y salidas anticipadas).

Nada de lo que hay aquí es asistencia registrada. Cada fila del archivo queda
«pendiente» hasta que el usuario confirma docente, fecha, tipo y las horas exactas que
no se cumplieron. Solo entonces se crean registros en ``asistencia_hora`` (en una sola
transacción) y la fila pasa a «importada». Una falta reportada nunca se convierte por sí
sola en ausencia de toda la jornada: sin horas elegidas, la fila sigue pendiente.

Estados de la fila:
- pendiente: leída del archivo; se puede corregir.
- importada: sus horas ya están en la asistencia por hora (no se vuelve a importar).
- descartada: el usuario decidió no importarla (se conserva como evidencia).
"""

from datetime import date, datetime, time
from typing import Any

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

from app.db.tipos import FechaHora, JSONCompatible
from app.models.base import Base, ConFechas
from app.models.catalogos import Docente


class ImportacionIncidencias(ConFechas, Base):
    """Un archivo Excel de incidencias. El mismo archivo no se registra dos veces."""

    __tablename__ = "importacion_incidencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_archivo: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    hoja: Mapped[str] = mapped_column(String(100), default="")
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    total_filas: Mapped[int] = mapped_column(Integer, default=0)

    filas: Mapped[list["IncidenciaImportada"]] = relationship(
        back_populates="importacion", order_by="IncidenciaImportada.fila"
    )


class IncidenciaImportada(ConFechas, Base):
    """Una fila del archivo: lo que decía (evidencia) y lo que el usuario confirmó."""

    __tablename__ = "incidencia_importada"
    __table_args__ = (
        UniqueConstraint("importacion_id", "fila", name="uq_incidencia_importada_fila"),
        CheckConstraint("estado IN ('pendiente', 'importada', 'descartada')", name="estado"),
        CheckConstraint("tipo IS NULL OR tipo IN ('falta', 'salida_anticipada')", name="tipo"),
        CheckConstraint(
            "docente_estado IN ('coincide', 'sugerido', 'sin_coincidencia', 'confirmado')",
            name="docente_estado",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    importacion_id: Mapped[int] = mapped_column(
        ForeignKey("importacion_incidencias.id"), index=True
    )
    fila: Mapped[int] = mapped_column(Integer)  # número de fila en la hoja de Excel

    # Texto original del archivo (no se modifica: es la evidencia).
    fecha_texto: Mapped[str] = mapped_column(String(60), default="")
    docente_texto: Mapped[str] = mapped_column(String(200), default="")
    tipo_texto: Mapped[str] = mapped_column(String(200), default="")
    detalle_texto: Mapped[str] = mapped_column(Text, default="")

    # Valores interpretados o corregidos por el usuario.
    fecha: Mapped[date | None] = mapped_column(Date, index=True)
    docente_id: Mapped[int | None] = mapped_column(ForeignKey("docente.id"), index=True)
    docente_estado: Mapped[str] = mapped_column(String(20), default="sin_coincidencia")
    tipo: Mapped[str | None] = mapped_column(String(20))
    hora_salida: Mapped[time | None] = mapped_column(Time)
    # Horas elegidas: [{"bloque_id": 3, "programado_inicio": "19:00:00"}, …]
    horas: Mapped[list[dict[str, Any]]] = mapped_column(JSONCompatible, default=list)
    justificada: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo: Mapped[str] = mapped_column(Text, default="")
    observaciones: Mapped[str] = mapped_column(Text, default="")
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id"))

    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    asistencias: Mapped[list[int]] = mapped_column(JSONCompatible, default=list)
    importada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    importada_en: Mapped[datetime | None] = mapped_column(FechaHora())

    importacion: Mapped[ImportacionIncidencias] = relationship(back_populates="filas")
    docente: Mapped[Docente | None] = relationship(lazy="joined")
