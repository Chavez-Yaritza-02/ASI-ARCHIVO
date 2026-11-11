"""Inicio de sesión y datos del usuario actual."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import SesionDB, UsuarioActual
from app.core.seguridad import crear_token, verificar_contrasena
from app.models import Auditoria, Usuario

router = APIRouter(prefix="/auth", tags=["autenticación"])


class TokenRespuesta(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioRespuesta(BaseModel):
    id: int
    correo: str
    nombre: str
    roles: list[str]
    permisos: list[str]


@router.post("/login", response_model=TokenRespuesta)
def login(
    sesion: SesionDB,
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenRespuesta:
    # El formulario OAuth2 llama "username" al campo; aquí es el correo.
    correo = form.username.strip().lower()
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo))
    ip = request.client.host if request.client else None

    if (
        usuario is None
        or not usuario.activo
        or not verificar_contrasena(form.password, usuario.hash_contrasena)
    ):
        sesion.add(
            Auditoria(accion="login_fallido", entidad="usuario", despues={"correo": correo}, ip=ip)
        )
        sesion.commit()
        # Mismo mensaje en todos los casos para no revelar qué correos existen.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos")

    sesion.add(Auditoria(usuario_id=usuario.id, accion="login", entidad="usuario", ip=ip))
    sesion.commit()
    return TokenRespuesta(access_token=crear_token(usuario.id))


@router.get("/yo", response_model=UsuarioRespuesta)
def usuario_conectado(usuario: UsuarioActual) -> UsuarioRespuesta:
    return UsuarioRespuesta(
        id=usuario.id,
        correo=usuario.correo,
        nombre=usuario.nombre,
        roles=sorted(r.nombre for r in usuario.roles),
        permisos=sorted(usuario.permisos),
    )
