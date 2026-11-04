"""Esquemas de entrada y salida de horarios."""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from asi_shared import DiaSemana, EstadoHorario, OrigenHorario

ORDEN_DIAS = list(DiaSemana)


class Referencia(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str


class ReferenciaClave(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    clave: str


class GrupoRef(ReferenciaClave):
    pendiente_validacion: bool


class AsignaturaRef(Referencia):
    tipo: str


class PeriodoRef(Referencia):
    estado: str


class BloqueEntrada(BaseModel):
    dia: DiaSemana
    hora_inicio: time
    hora_fin: time
    asignatura_id: int
    grupo_id: int | None = None
    grupo_letra: str | None = Field(default=None, max_length=5)
    aula_id: int | None = None


class BloqueSalida(BaseModel):
    dia: DiaSemana
    hora_inicio: time
    hora_fin: time
    asignatura: AsignaturaRef
    grupo: GrupoRef | None
    grupo_letra: str | None = None
    aula: ReferenciaClave | None


class HorarioCrear(BaseModel):
    docente_id: int
    periodo_id: int
    basado_en_id: int | None = Field(
        default=None, description="Versión cuyos bloques se copian al nuevo borrador"
    )
    origen: OrigenHorario = OrigenHorario.MANUAL
    notas: str = ""


class HorarioEditar(BaseModel):
    notas: str


class Confirmacion(BaseModel):
    aceptar_advertencias: bool = False
    vigente_desde: date | None = Field(
        default=None, description="Desde cuándo rige (por omisión: inicio del periodo u hoy)"
    )


class HorarioResumen(BaseModel):
    id: int
    docente: Referencia
    periodo: PeriodoRef
    version: int
    estado: EstadoHorario
    origen: OrigenHorario
    notas: str
    horas: float
    basado_en_id: int | None
    creado_en: datetime
    confirmado_en: datetime | None
    vigente_desde: date | None = None
    vigente_hasta: date | None = None


class HorarioDetalle(HorarioResumen):
    fecha_documento: date | None
    version_documento: int | None
    bloques: list[BloqueSalida]
    advertencias: list[str] = []


def _horas(horario) -> float:
    total = 0.0
    for b in horario.bloques:
        total += (
            datetime.combine(date.min, b.hora_fin) - datetime.combine(date.min, b.hora_inicio)
        ).seconds / 3600
    return round(total, 2)


def resumen(horario) -> HorarioResumen:
    return HorarioResumen(
        id=horario.id,
        docente=Referencia.model_validate(horario.docente),
        periodo=PeriodoRef.model_validate(horario.periodo),
        version=horario.version,
        estado=horario.estado,
        origen=horario.origen,
        notas=horario.notas,
        horas=_horas(horario),
        basado_en_id=horario.basado_en_id,
        creado_en=horario.creado_en,
        confirmado_en=horario.confirmado_en,
        vigente_desde=horario.vigente_desde,
        vigente_hasta=horario.vigente_hasta,
    )


def detalle(horario, advertencias: list[str] | None = None) -> HorarioDetalle:
    return HorarioDetalle(
        **resumen(horario).model_dump(),
        fecha_documento=horario.fecha_documento,
        version_documento=horario.version_documento,
        bloques=[
            BloqueSalida(
                dia=ORDEN_DIAS[b.dia],
                hora_inicio=b.hora_inicio,
                hora_fin=b.hora_fin,
                asignatura=AsignaturaRef.model_validate(b.asignatura),
                grupo=GrupoRef.model_validate(b.grupo) if b.grupo else None,
                grupo_letra=b.grupo_letra,
                aula=ReferenciaClave.model_validate(b.aula) if b.aula else None,
            )
            for b in horario.bloques
        ],
        advertencias=advertencias or [],
    )
