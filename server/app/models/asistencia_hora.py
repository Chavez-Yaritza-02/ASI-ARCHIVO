"""Asistencia por tramo de clase, independiente del registro legado por turno."""

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
    and_,
    literal_column,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.tipos import segundos_entre
from app.models.base import Base, ConFechas

DURACION = segundos_entre("programado_fin", "programado_inicio")


class AsistenciaHora(ConFechas, Base):
    __tablename__ = "asistencia_hora"
    __table_args__ = (
        UniqueConstraint(
            "docente_id",
            "fecha",
            "programado_inicio",
            name="uq_asistencia_hora_docente_fecha_inicio",
        ),
        CheckConstraint(
            "estado IN ('asistio','retardo','falto','justificado','parcial')", name="estado"
        ),
        CheckConstraint("turno IN ('matutino','vespertino')", name="turno"),
        # La duración se escribe en la sintaxis de cada base (ver app.db.tipos).
        CheckConstraint(
            and_(
                text("programado_fin > programado_inicio"),
                DURACION <= 3600,
            ),
            name="tramo",
        ),
        CheckConstraint(
            and_(
                text("minutos_cumplidos >= 0 AND minutos_justificados >= 0"),
                literal_column("(minutos_cumplidos + minutos_justificados) * 60") <= DURACION,
            ),
            name="minutos",
        ),
        CheckConstraint(
            "hora_salida IS NULL OR hora_entrada IS NULL OR hora_salida > hora_entrada",
            name="horas",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    docente_id: Mapped[int] = mapped_column(ForeignKey("docente.id"), index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("periodo.id"))
    horario_id: Mapped[int] = mapped_column(ForeignKey("horario.id"))
    bloque_id: Mapped[int] = mapped_column(ForeignKey("bloque_horario.id"))
    # Copia inmutable del programa y nombres al capturar; nunca se reasigna por corrección.
    docente_nombre: Mapped[str] = mapped_column(String(150))
    asignatura: Mapped[str] = mapped_column(String(120))
    tipo_actividad: Mapped[str] = mapped_column(String(20))
    grupo: Mapped[str | None] = mapped_column(String(80))
    aula: Mapped[str | None] = mapped_column(String(30))
    turno: Mapped[str] = mapped_column(String(12))
    programado_inicio: Mapped[time] = mapped_column(Time)
    programado_fin: Mapped[time] = mapped_column(Time)
    estado: Mapped[str] = mapped_column(String(15))
    hora_entrada: Mapped[time | None] = mapped_column(Time)
    hora_salida: Mapped[time | None] = mapped_column(Time)
    minutos_cumplidos: Mapped[int] = mapped_column(Integer)
    minutos_justificados: Mapped[int] = mapped_column(Integer)
    observaciones: Mapped[str] = mapped_column(Text, default="")
    justificacion: Mapped[str] = mapped_column(Text, default="")
    en_dia_inhabil: Mapped[bool] = mapped_column(Boolean, default=False)
    registrado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    correcciones: Mapped[int] = mapped_column(Integer, default=0)
