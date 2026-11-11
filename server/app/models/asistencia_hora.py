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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ConFechas


def _restricciones_de_tramo(segundos: str, motor: str) -> tuple[CheckConstraint, ...]:
    """Tramo de una hora como máximo y minutos acreditados que caben en el tramo."""
    sufijo = "" if motor == "postgresql" else "_local"
    return (
        CheckConstraint(
            f"programado_fin > programado_inicio AND {segundos} <= 3600", name=f"tramo{sufijo}"
        ).ddl_if(dialect=motor),
        CheckConstraint(
            "minutos_cumplidos >= 0 AND minutos_justificados >= 0 AND "
            f"(minutos_cumplidos + minutos_justificados) * 60 <= {segundos}",
            name=f"minutos{sufijo}",
        ).ddl_if(dialect=motor),
    )


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
        # La duración se calcula distinto en cada motor; cada restricción se crea solo
        # en el suyo (PostgreSQL: servidor central; SQLite: modo local).
        *_restricciones_de_tramo(
            "EXTRACT(EPOCH FROM (programado_fin-programado_inicio))", "postgresql"
        ),
        *_restricciones_de_tramo(
            "(strftime('%s', '2000-01-01 ' || programado_fin) - "
            "strftime('%s', '2000-01-01 ' || programado_inicio))",
            "sqlite",
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
