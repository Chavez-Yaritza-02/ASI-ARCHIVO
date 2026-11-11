"""Buscador, horarios por grupo y ubicación programada con permisos existentes."""

from datetime import date, datetime, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.bitacora import _archivo
from app.api.deps import SesionDB, UsuarioActual, requiere_permiso
from app.core.config import obtener_configuracion
from app.models import Grupo, Usuario
from app.reports import grupos as reportes
from app.services import configuracion, consultas
from app.services.comun import hoy
from asi_shared import Turno

router = APIRouter(tags=["consultas"])
Lector = Annotated[Usuario, Depends(requiere_permiso("horarios.ver"))]
Asistencia = Annotated[Usuario, Depends(requiere_permiso("asistencia.ver"))]
Docentes = Annotated[Usuario, Depends(requiere_permiso("docentes.ver"))]
Reportero = Annotated[Usuario, Depends(requiere_permiso("reportes.generar"))]


@router.get("/consultas/ahora")
def ahora(_: UsuarioActual):
    zona = obtener_configuracion().zona_horaria
    instante = datetime.now(ZoneInfo(zona))
    return {"fecha": instante.date(), "hora": instante.time().replace(tzinfo=None), "zona": zona}


def filtros(
    carrera: str | None = Query(None, min_length=1, max_length=60),
    semestre: int | None = Query(None, ge=1, le=12),
    periodo_id: int | None = Query(None, ge=1),
):
    return {"carrera": carrera, "semestre": semestre, "periodo_id": periodo_id}


@router.get("/buscador")
def buscar(
    sesion: SesionDB,
    usuario: UsuarioActual,
    filtros: Annotated[dict, Depends(filtros)],
    texto: str = Query("", max_length=150),
    fecha: date | None = None,
    dia: int | None = Query(None, ge=0, le=5),
    turno: Turno | None = None,
    limite: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if not {"docentes.ver", "horarios.ver"} & usuario.permisos:
        raise HTTPException(403, "No tienes permiso para buscar")
    # Un filtro de horarios no puede convertirse en un canal lateral sin permiso.
    if "horarios.ver" not in usuario.permisos and (
        any(v is not None for v in filtros.values()) or dia is not None or turno is not None
    ):
        raise HTTPException(403, "Los filtros de horarios requieren horarios.ver")
    return consultas.buscar(
        sesion,
        usuario.permisos,
        texto,
        fecha or hoy(),
        **filtros,
        dia=dia,
        turno=turno,
        limite=limite,
        offset=offset,
    )


@router.get("/consultas/grupos")
def grupos(
    sesion: SesionDB,
    _: Lector,
    filtros: Annotated[dict, Depends(filtros)],
    letra: str | None = Query(None, max_length=5),
):
    return [
        {
            "id": g.id,
            "clave": g.clave,
            "carrera": g.carrera,
            "semestre": g.semestre,
            "letra": g.letra,
            "periodo_id": g.periodo_id,
        }
        for g in sesion.scalars(select(Grupo).order_by(Grupo.clave))
        if consultas.coincide_grupo(g, **filtros, letra=letra)
    ]


@router.get("/consultas/grupos/{id_}/horario")
def horario_grupo(id_: int, sesion: SesionDB, _: Lector, _a: Asistencia, fecha: date):
    return consultas.grupo_semanal(sesion, id_, fecha)


@router.get("/consultas/grupos/{id_}/exportar")
def exportar_grupo(
    id_: int,
    sesion: SesionDB,
    _: Lector,
    _a: Asistencia,
    _r: Reportero,
    fecha: date,
    formato: Literal["pdf", "xlsx"] = "pdf",
):
    datos = consultas.grupo_semanal(sesion, id_, fecha)
    return _archivo(reportes.exportar(datos, formato), formato, f"grupo_{id_}_{datos['desde']}")


@router.get("/consultas/docentes/{id_}/ubicacion")
def ubicacion(
    id_: int,
    sesion: SesionDB,
    _: Lector,
    _a: Asistencia,
    _d: Docentes,
    fecha: date | None = None,
    hora: time | None = None,
):
    ahora = datetime.now(ZoneInfo(obtener_configuracion().zona_horaria))
    if hora is not None and hora.tzinfo is not None:
        raise HTTPException(422, "Usa la hora local de la Jefatura sin desplazamiento UTC")
    return consultas.ubicacion(
        sesion, id_, fecha or ahora.date(), hora or ahora.time().replace(tzinfo=None)
    )


class Tolerancia(BaseModel):
    tolerancia_minutos: int = Field(ge=0, le=120)


def administrador(usuario: UsuarioActual):
    if "administrador" not in {r.nombre for r in usuario.roles}:
        raise HTTPException(403, "Solo un administrador puede configurar la tolerancia")
    return usuario


@router.get("/configuracion/asistencia")
def ver_configuracion(sesion: SesionDB, _: Asistencia):
    return {"tolerancia_minutos": configuracion.tolerancia(sesion)}


@router.put("/configuracion/asistencia")
def configurar(
    datos: Tolerancia, sesion: SesionDB, usuario: Annotated[Usuario, Depends(administrador)]
):
    return configuracion.actualizar_tolerancia(sesion, usuario, datos.tolerancia_minutos)
