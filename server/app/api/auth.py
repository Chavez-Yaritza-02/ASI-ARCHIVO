"""Inicio de sesión y datos del usuario actual."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.api.deps import SesionDB, UsuarioActual
from app.core.seguridad import crear_token, sello_usuario, verificar_contrasena
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
    ip = request.client.host if request.client else None
    # Serializar por IP evita que peticiones simultáneas eludan el contador.
    # En SQLite (aplicación local) solo hay un escritor a la vez: la transacción ya es exclusiva.
    if sesion.get_bind().dialect.name == "postgresql":
        sesion.execute(text("SELECT pg_advisory_xact_lock(hashtext(:ip))"), {"ip": ip or "sin-ip"})
    fallos = sesion.scalar(
        select(func.count())
        .select_from(Auditoria)
        .where(
            Auditoria.accion == "login_fallido",
            Auditoria.ip == ip,
            Auditoria.fecha >= datetime.now(UTC) - timedelta(minutes=15),
        )
    )
    if fallos >= 10:
        sesion.add(Auditoria(accion="login_limitado", entidad="usuario", ip=ip))
        sesion.commit()
        raise HTTPException(
            429, "Demasiados intentos; espera 15 minutos", headers={"Retry-After": "900"}
        )
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo))

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
    return TokenRespuesta(access_token=crear_token(usuario.id, sello_usuario(usuario)))


@router.get("/yo", response_model=UsuarioRespuesta)
def usuario_conectado(usuario: UsuarioActual) -> UsuarioRespuesta:
    return UsuarioRespuesta(
        id=usuario.id,
        correo=usuario.correo,
        nombre=usuario.nombre,
        roles=sorted(r.nombre for r in usuario.roles),
        permisos=sorted(usuario.permisos),
    )
