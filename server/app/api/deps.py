"""Dependencias comunes de los endpoints: usuario autenticado y permisos."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.seguridad import leer_token, sesion_vigente
from app.db.sesion import obtener_sesion
from app.models import Usuario

_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

SesionDB = Annotated[Session, Depends(obtener_sesion)]


def usuario_actual(sesion: SesionDB, token: Annotated[str, Depends(_oauth2)]) -> Usuario:
    usuario_id = leer_token(token)
    usuario = sesion.get(Usuario, usuario_id) if usuario_id is not None else None
    if usuario is None or not usuario.activo or not sesion_vigente(token, usuario):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión inválida o expirada",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario


UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]


def requiere_permiso(clave: str) -> Callable[[Usuario], Usuario]:
    """Uso: `Depends(requiere_permiso(Permiso.DOCENTES_EDITAR))`."""

    def verificar(usuario: UsuarioActual) -> Usuario:
        if clave not in usuario.permisos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para esta acción")
        return usuario

    return verificar
