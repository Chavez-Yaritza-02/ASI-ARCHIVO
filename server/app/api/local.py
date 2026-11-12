"""Rutas de la aplicación local: primera ejecución y recuperación de la contraseña.

Solo responden en modo local (`ASI_MODO_LOCAL`); en el servidor institucional dan 404.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import SesionDB, UsuarioActual
from app.core.config import obtener_configuracion
from app.local import cuenta


def _solo_modo_local() -> None:
    if not obtener_configuracion().modo_local:
        raise HTTPException(404, "Not Found")


router = APIRouter(
    prefix="/local", tags=["aplicación local"], dependencies=[Depends(_solo_modo_local)]
)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class EstadoLocal(BaseModel):
    configurada: bool
    usuario: str | None


class CuentaNueva(BaseModel):
    usuario: Annotated[str, Field(max_length=120)]
    nombre: Annotated[str, Field(max_length=120)]
    contrasena: Annotated[str, Field(max_length=128)]


class Recuperacion(BaseModel):
    usuario: Annotated[str, Field(max_length=120)]
    codigo: Annotated[str, Field(max_length=64)]
    nueva: Annotated[str, Field(max_length=128)]


class Confirmacion(BaseModel):
    contrasena: Annotated[str, Field(max_length=128)]


class CodigoRecuperacion(BaseModel):
    usuario: str
    codigo_recuperacion: str


@router.get("/estado", response_model=EstadoLocal)
def estado(sesion: SesionDB) -> EstadoLocal:
    return EstadoLocal(
        configurada=cuenta.hay_cuenta(sesion), usuario=cuenta.usuario_de_la_cuenta(sesion)
    )


@router.post("/cuenta", response_model=CodigoRecuperacion, status_code=201)
def crear_cuenta(datos: CuentaNueva, sesion: SesionDB, request: Request) -> CodigoRecuperacion:
    codigo = cuenta.crear_cuenta(
        sesion, datos.usuario, datos.nombre, datos.contrasena, _ip(request)
    )
    return CodigoRecuperacion(
        usuario=cuenta.normalizar_usuario(datos.usuario), codigo_recuperacion=codigo
    )


@router.post("/recuperar", response_model=CodigoRecuperacion)
def recuperar(datos: Recuperacion, sesion: SesionDB, request: Request) -> CodigoRecuperacion:
    codigo = cuenta.recuperar(sesion, datos.usuario, datos.codigo, datos.nueva, _ip(request))
    return CodigoRecuperacion(usuario=datos.usuario.strip().lower(), codigo_recuperacion=codigo)


@router.post("/codigo", response_model=CodigoRecuperacion)
def renovar_codigo(
    datos: Confirmacion, sesion: SesionDB, usuario: UsuarioActual, request: Request
) -> CodigoRecuperacion:
    codigo = cuenta.renovar_codigo(sesion, usuario, datos.contrasena, _ip(request))
    return CodigoRecuperacion(usuario=usuario.correo, codigo_recuperacion=codigo)
