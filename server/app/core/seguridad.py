"""Contraseñas (Argon2) y tokens de sesión (JWT)."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import obtener_configuracion

_hasher = PasswordHasher()
_ALGORITMO = "HS256"


def hashear_contrasena(contrasena: str) -> str:
    return _hasher.hash(contrasena)


def verificar_contrasena(contrasena: str, hash_guardado: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, contrasena)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sello_usuario(usuario) -> str:
    material = f"{usuario.hash_contrasena}:{usuario.actualizado_en.astimezone(UTC).isoformat()}"
    return hmac.new(
        obtener_configuracion().secret_key.encode(), material.encode(), hashlib.sha256
    ).hexdigest()


def crear_token(usuario_id: int, sello: str | None = None) -> str:
    config = obtener_configuracion()
    ahora = datetime.now(UTC)
    datos = {
        "sub": str(usuario_id),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=config.token_minutos),
        "sesion": sello,
    }
    return jwt.encode(datos, config.secret_key, algorithm=_ALGORITMO)


def sesion_vigente(token: str, usuario) -> bool:
    try:
        datos = jwt.decode(token, obtener_configuracion().secret_key, algorithms=[_ALGORITMO])
        return isinstance(datos.get("sesion"), str) and hmac.compare_digest(
            datos["sesion"], sello_usuario(usuario)
        )
    except jwt.PyJWTError:
        return False


def leer_token(token: str) -> int | None:
    """Devuelve el id del usuario, o None si el token es inválido o expiró."""
    try:
        datos = jwt.decode(token, obtener_configuracion().secret_key, algorithms=[_ALGORITMO])
        return int(datos["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
