"""Endpoints de docentes, asignaturas, grupos y aulas.

Los cuatro catálogos se comportan igual (listar, consultar, crear, editar, activar,
desactivar), así que sus rutas se generan con una sola función.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import SesionDB, requiere_permiso
from app.models import Usuario
from app.schemas.catalogos import (
    AsignaturaCrear,
    AsignaturaEditar,
    AsignaturaSalida,
    ClaveCrear,
    ClaveEditar,
    ClaveSalida,
    DocenteCrear,
    DocenteEditar,
    DocenteSalida,
    GrupoCrear,
    GrupoEditar,
    GrupoSalida,
)
from app.services import catalogos as servicio
from asi_shared import Permiso


def crear_router(
    entidad: str,
    prefijo: str,
    etiqueta: str,
    entrada: type[BaseModel],
    edicion: type[BaseModel],
    salida: type[BaseModel],
    permiso_ver: str,
    permiso_editar: str,
) -> APIRouter:
    router = APIRouter(prefix=prefijo, tags=[etiqueta])
    Lector = Annotated[Usuario, Depends(requiere_permiso(permiso_ver))]
    Editor = Annotated[Usuario, Depends(requiere_permiso(permiso_editar))]

    @router.get("", response_model=list[salida])
    def listar(
        sesion: SesionDB,
        _: Lector,
        buscar: str = "",
        activo: Annotated[bool | None, Query(description="Filtra por estado")] = None,
        periodo_id: Annotated[int | None, Query(description="Solo grupos")] = None,
    ):
        return servicio.listar(sesion, entidad, buscar, activo, periodo_id)

    @router.get("/{id_}", response_model=salida)
    def consultar(id_: int, sesion: SesionDB, _: Lector):
        return servicio.obtener(sesion, entidad, id_)

    @router.post("", response_model=salida, status_code=201)
    def crear(datos: entrada, sesion: SesionDB, usuario: Editor):  # type: ignore[valid-type]
        return servicio.crear(sesion, usuario, entidad, datos.model_dump())

    @router.patch("/{id_}", response_model=salida)
    def editar(id_: int, cambios: edicion, sesion: SesionDB, usuario: Editor):  # type: ignore[valid-type]
        return servicio.editar(
            sesion, usuario, entidad, id_, cambios.model_dump(exclude_unset=True)
        )

    @router.post("/{id_}/activar", response_model=salida)
    def activar(id_: int, sesion: SesionDB, usuario: Editor):
        return servicio.editar(sesion, usuario, entidad, id_, {"activo": True})

    @router.post("/{id_}/desactivar", response_model=salida)
    def desactivar(id_: int, sesion: SesionDB, usuario: Editor):
        return servicio.editar(sesion, usuario, entidad, id_, {"activo": False})

    return router


docentes = crear_router(
    "docente",
    "/docentes",
    "docentes",
    DocenteCrear,
    DocenteEditar,
    DocenteSalida,
    Permiso.DOCENTES_VER,
    Permiso.DOCENTES_EDITAR,
)
asignaturas = crear_router(
    "asignatura",
    "/asignaturas",
    "catálogos",
    AsignaturaCrear,
    AsignaturaEditar,
    AsignaturaSalida,
    Permiso.HORARIOS_VER,
    Permiso.HORARIOS_EDITAR,
)
grupos = crear_router(
    "grupo",
    "/grupos",
    "catálogos",
    GrupoCrear,
    GrupoEditar,
    GrupoSalida,
    Permiso.HORARIOS_VER,
    Permiso.HORARIOS_EDITAR,
)
aulas = crear_router(
    "aula",
    "/aulas",
    "catálogos",
    ClaveCrear,
    ClaveEditar,
    ClaveSalida,
    Permiso.HORARIOS_VER,
    Permiso.HORARIOS_EDITAR,
)
