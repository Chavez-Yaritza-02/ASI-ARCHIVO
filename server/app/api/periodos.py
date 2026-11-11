"""Endpoints de periodos académicos."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SesionDB, requiere_permiso
from app.models import Usuario
from app.schemas.catalogos import PeriodoEntrada, PeriodoSalida
from app.services import periodos as servicio
from asi_shared import Permiso

router = APIRouter(prefix="/periodos", tags=["periodos"])
# Consultar periodos es necesario para ver horarios, así que basta con horarios.ver.
Lector = Annotated[Usuario, Depends(requiere_permiso(Permiso.HORARIOS_VER))]
Gestor = Annotated[Usuario, Depends(requiere_permiso(Permiso.PERIODOS_GESTIONAR))]


@router.get("", response_model=list[PeriodoSalida])
def listar(sesion: SesionDB, _: Lector):
    return servicio.listar(sesion)


@router.get("/activo", response_model=PeriodoSalida | None)
def periodo_activo(sesion: SesionDB, _: Lector):
    return servicio.activo(sesion)


@router.get("/{id_}", response_model=PeriodoSalida)
def consultar(id_: int, sesion: SesionDB, _: Lector):
    return servicio.obtener(sesion, id_)


@router.post("", response_model=PeriodoSalida, status_code=201)
def crear(datos: PeriodoEntrada, sesion: SesionDB, usuario: Gestor):
    return servicio.crear(sesion, usuario, datos.nombre, datos.fecha_inicio, datos.fecha_fin)


@router.put("/{id_}", response_model=PeriodoSalida)
def editar(id_: int, datos: PeriodoEntrada, sesion: SesionDB, usuario: Gestor):
    return servicio.editar(sesion, usuario, id_, datos.nombre, datos.fecha_inicio, datos.fecha_fin)


@router.post("/{id_}/activar", response_model=PeriodoSalida)
def activar(id_: int, sesion: SesionDB, usuario: Gestor):
    return servicio.activar(sesion, usuario, id_)


@router.post("/{id_}/cerrar", response_model=PeriodoSalida)
def cerrar(id_: int, sesion: SesionDB, usuario: Gestor):
    return servicio.cerrar(sesion, usuario, id_)
