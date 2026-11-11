"""Contraseñas (Argon2) y tokens de sesión (JWT)."""

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


def crear_token(usuario_id: int) -> str:
    config = obtener_configuracion()
    ahora = datetime.now(UTC)
    datos = {
        "sub": str(usuario_id),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=config.token_minutos),
    }
    return jwt.encode(datos, config.secret_key, algorithm=_ALGORITMO)


def leer_token(token: str) -> int | None:
    """Devuelve el id del usuario, o None si el token es inválido o expiró."""
    try:
        datos = jwt.decode(token, obtener_configuracion().secret_key, algorithms=[_ALGORITMO])
        return int(datos["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
