"""Importación de faltas y salidas anticipadas desde Excel (zona de revisión).

Subir y revisar requiere `asistencia.registrar`; importar (crear las horas en la
asistencia por hora, días ya pasados) requiere además `asistencia.corregir`.
"""

from datetime import date, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import SesionDB, requiere_permiso
from app.importers.incidencias_excel import TAMANO_MAXIMO
from app.models import Usuario
from app.services import incidencias_excel as servicio
from asi_shared import Permiso

router = APIRouter(prefix="/incidencias-excel", tags=["incidencias desde Excel"])
Registrador = Annotated[Usuario, Depends(requiere_permiso(Permiso.ASISTENCIA_REGISTRAR))]


class HoraElegida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bloque_id: int = Field(ge=1)
    programado_inicio: time


class FilaEdicion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fecha: date | None = None
    docente_id: int | None = Field(None, ge=1)
    tipo: Literal["falta", "salida_anticipada"] | None = None
    hora_salida: time | None = None
    horas: list[HoraElegida] | None = Field(None, max_length=24)
    justificada: bool | None = None
    motivo: str | None = Field(None, max_length=1000)
    observaciones: str | None = Field(None, max_length=1000)
    documento_id: int | None = Field(None, ge=1)


class Descarte(BaseModel):
    model_config = ConfigDict(extra="forbid")
    motivo: str = Field(min_length=5, max_length=1000)


class Importar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filas: list[int] = Field(min_length=1, max_length=500)


@router.post("", status_code=201)
async def cargar(
    sesion: SesionDB,
    usuario: Registrador,
    response: Response,
    archivo: Annotated[UploadFile, File(description="Excel (.xlsx) con las incidencias")],
):
    """Lee el archivo y deja sus filas pendientes de revisión. No registra asistencia."""
    contenido = await archivo.read(TAMANO_MAXIMO + 1)
    importacion, nueva = servicio.cargar(sesion, usuario, contenido, archivo.filename or "")
    if not nueva:
        response.status_code = 200
    return {**servicio.detalle(sesion, importacion), "ya_existia": not nueva}


@router.get("")
def listar(sesion: SesionDB, _: Registrador):
    return servicio.listar(sesion)


@router.get("/{id_}")
def consultar(id_: int, sesion: SesionDB, _: Registrador):
    return servicio.detalle(sesion, servicio.obtener(sesion, id_))


@router.get("/filas/{fila_id}/horas")
def horas(fila_id: int, sesion: SesionDB, _: Registrador):
    return servicio.horas(sesion, fila_id)


@router.patch("/filas/{fila_id}")
def editar(fila_id: int, datos: FilaEdicion, sesion: SesionDB, usuario: Registrador):
    cambios = datos.model_dump(exclude_unset=True)
    fila = servicio.editar(sesion, usuario, fila_id, cambios)
    return servicio.salida(sesion, fila)


@router.post("/filas/{fila_id}/descartar")
def descartar(fila_id: int, datos: Descarte, sesion: SesionDB, usuario: Registrador):
    return servicio.salida(
        sesion, servicio.cambiar_estado(sesion, usuario, fila_id, True, datos.motivo)
    )


@router.post("/filas/{fila_id}/recuperar")
def recuperar(fila_id: int, sesion: SesionDB, usuario: Registrador):
    return servicio.salida(sesion, servicio.cambiar_estado(sesion, usuario, fila_id, False))


@router.post("/{id_}/importar")
def importar(id_: int, datos: Importar, sesion: SesionDB, usuario: Registrador):
    """Registra SOLO las filas indicadas (confirmadas). Si una falla, no se guarda ninguna."""
    resultado = servicio.importar(sesion, usuario, id_, datos.filas)
    return {**resultado, "importacion": servicio.detalle(sesion, servicio.obtener(sesion, id_))}
