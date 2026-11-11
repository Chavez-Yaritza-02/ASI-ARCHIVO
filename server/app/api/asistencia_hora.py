"""API de asistencia por hora: permisos existentes, captura y corrección auditadas."""

from datetime import date, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.bitacora import _archivo
from app.api.deps import SesionDB, requiere_permiso
from app.models import Usuario
from app.reports import asistencia_hora as reportes
from app.services import asistencia_hora as servicio
from asi_shared import Turno

router = APIRouter(tags=["asistencia por hora"])
Lector = Annotated[Usuario, Depends(requiere_permiso("asistencia.ver"))]
Registrador = Annotated[Usuario, Depends(requiere_permiso("asistencia.registrar"))]
Reportero = Annotated[Usuario, Depends(requiere_permiso("reportes.generar"))]
Estado = Literal["asistio", "retardo", "falto", "justificado", "parcial"]


class DatosRegistro(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado: Estado
    hora_entrada: time | None = None
    hora_salida: time | None = None
    minutos_justificados: int = Field(0, ge=0, le=60)
    observaciones: str = Field("", max_length=1000)
    justificacion: str = Field("", max_length=1000)


class RegistroEntrada(DatosRegistro):
    docente_id: int = Field(ge=1)
    fecha: date
    bloque_id: int = Field(ge=1)
    programado_inicio: time
    autorizar_dia_inhabil: bool = False


class CorreccionEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    motivo: str = Field(min_length=5, max_length=1000)
    estado: Estado | None = None
    hora_entrada: time | None = None
    hora_salida: time | None = None
    minutos_justificados: int | None = Field(None, ge=0, le=60)
    observaciones: str | None = Field(None, max_length=1000)
    justificacion: str | None = Field(None, max_length=1000)


class LoteEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registros: list[RegistroEntrada] = Field(min_length=1, max_length=100)


@router.post("/asistencias/horas/lote", status_code=201)
def registrar_lote(datos: LoteEntrada, sesion: SesionDB, usuario: Registrador):
    return servicio.registrar_lote(sesion, usuario, [r.model_dump() for r in datos.registros])


def filtros(
    docente_id: int | None = Query(None, ge=1),
    turno: Turno | None = None,
    estado: Literal["pendiente", "inhabil", "asistio", "retardo", "falto", "justificado", "parcial"]
    | None = None,
    tipo_actividad: Literal["materia", "actividad"] | None = None,
):
    return {
        "docente_id": docente_id,
        "turno": turno,
        "estado": estado,
        "tipo_actividad": tipo_actividad,
    }


@router.get("/bitacora/horas")
def dia(sesion: SesionDB, _: Lector, fecha: date, filtros: Annotated[dict, Depends(filtros)]):
    return servicio.dia(sesion, fecha, **filtros)


@router.post("/asistencias/horas", status_code=201)
def registrar(datos: RegistroEntrada, sesion: SesionDB, usuario: Registrador):
    campos = datos.model_dump(include=set(DatosRegistro.model_fields))
    return servicio.registrar(
        sesion,
        usuario,
        datos.docente_id,
        datos.fecha,
        datos.bloque_id,
        datos.programado_inicio,
        campos,
        datos.autorizar_dia_inhabil,
    )


@router.patch("/asistencias/horas/{id_}")
def corregir(id_: int, datos: CorreccionEntrada, sesion: SesionDB, usuario: Registrador):
    cambios = datos.model_dump(exclude_unset=True, exclude={"motivo"})
    return servicio.corregir(sesion, usuario, id_, cambios, datos.motivo)


@router.get("/asistencias/horas/{id_}/historial")
def historial(id_: int, sesion: SesionDB, _: Lector):
    return servicio.historial(sesion, id_)


@router.get("/bitacora/horas/reporte")
def reporte(
    sesion: SesionDB,
    _: Lector,
    _r: Reportero,
    desde: date,
    hasta: date,
    filtros: Annotated[dict, Depends(filtros)],
    formato: Literal["pdf", "xlsx"] = "pdf",
):
    datos = servicio.rango(sesion, desde, hasta, **filtros)
    return _archivo(reportes.exportar(datos, formato), formato, f"asistencia_horas_{desde}_{hasta}")


@router.get("/bitacora/horas/exportar")
def exportar_dia(
    sesion: SesionDB,
    _: Lector,
    _r: Reportero,
    fecha: date,
    filtros: Annotated[dict, Depends(filtros)],
    formato: Literal["pdf", "xlsx"] = "pdf",
):
    datos = servicio.rango(sesion, fecha, fecha, **filtros)
    return _archivo(reportes.exportar(datos, formato), formato, f"asistencia_horas_{fecha}")
