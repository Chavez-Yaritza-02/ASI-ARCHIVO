"""Cuenta única de administrador de la aplicación local y su recuperación sin internet.

- Hay una sola cuenta, con el rol «administrador» (todos los permisos).
- Al crearla se genera un **código de recuperación** de 25 caracteres (125 bits). Se muestra
  una vez; en la base solo queda su huella Argon2.
- Con el código se pone una contraseña nueva; en ese momento se genera un código nuevo y el
  anterior deja de servir.
- Los intentos fallidos se registran en la auditoría y se limitan igual que el inicio de
  sesión. La auditoría nunca se borra.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.seguridad import hashear_contrasena, verificar_contrasena
from app.local.modelos import cuenta_recuperacion
from app.models import Auditoria, Rol, Usuario
from app.services.comun import ErrorNegocio

LONGITUD_MINIMA = 10
# Alfabeto Crockford: sin I, L, O ni U para que no se confundan al copiarlo a mano.
_ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_EQUIVALENCIAS = str.maketrans({"O": "0", "I": "1", "L": "1"})
_GRUPOS, _LARGO_GRUPO = 5, 5
LIMITE_INTENTOS, MINUTOS_BLOQUEO = 10, 15
# Huella fija para comparar aun cuando el usuario no existe (mismo tiempo de respuesta).
_HUELLA_FICTICIA = hashear_contrasena("codigo-ficticio-sin-uso")


def generar_codigo() -> str:
    caracteres = "".join(secrets.choice(_ALFABETO) for _ in range(_GRUPOS * _LARGO_GRUPO))
    return "-".join(
        caracteres[i : i + _LARGO_GRUPO] for i in range(0, len(caracteres), _LARGO_GRUPO)
    )


def normalizar_codigo(codigo: str) -> str:
    """Acepta minúsculas, espacios, guiones y las letras O/I/L confundidas con 0/1."""
    limpio = "".join(c for c in codigo.upper() if c.isalnum()).translate(_EQUIVALENCIAS)
    return limpio


def validar_contrasena(contrasena: str) -> None:
    if len(contrasena) < LONGITUD_MINIMA:
        raise ErrorNegocio(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres", 422)
    if len(contrasena) > 128:
        raise ErrorNegocio("La contraseña no puede tener más de 128 caracteres", 422)


def normalizar_usuario(usuario: str) -> str:
    usuario = usuario.strip().lower()
    permitidos = set("abcdefghijklmnopqrstuvwxyz0123456789._-@")
    if not 3 <= len(usuario) <= 120 or set(usuario) - permitidos:
        raise ErrorNegocio(
            "El usuario debe tener de 3 a 120 caracteres: letras sin acento, números, "
            "punto, guion, guion bajo o @",
            422,
        )
    return usuario


def hay_cuenta(sesion: Session) -> bool:
    return bool(sesion.scalar(select(func.count()).select_from(Usuario)))


def usuario_de_la_cuenta(sesion: Session) -> str | None:
    """El usuario de la cuenta activa (para mostrarlo en la pantalla de inicio)."""
    return sesion.scalar(
        select(Usuario.correo).where(Usuario.activo.is_(True)).order_by(Usuario.id).limit(1)
    )


def _nuevo_codigo(sesion: Session, usuario: Usuario) -> str:
    codigo = generar_codigo()
    sesion.execute(
        delete(cuenta_recuperacion).where(cuenta_recuperacion.c.usuario_id == usuario.id)
    )
    sesion.execute(
        insert(cuenta_recuperacion).values(
            usuario_id=usuario.id, huella=hashear_contrasena(normalizar_codigo(codigo))
        )
    )
    return codigo


def crear_cuenta(sesion: Session, usuario: str, nombre: str, contrasena: str, ip) -> str:
    """Crea la única cuenta. Devuelve el código de recuperación (se muestra una sola vez)."""
    if hay_cuenta(sesion):
        raise ErrorNegocio("La aplicación ya tiene su cuenta de administrador", 409)
    usuario = normalizar_usuario(usuario)
    nombre = " ".join(nombre.split())
    if not 3 <= len(nombre) <= 120:
        raise ErrorNegocio("Escribe el nombre de quien usará la aplicación", 422)
    validar_contrasena(contrasena)
    rol = sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
    if rol is None:
        raise ErrorNegocio("Falta el rol de administrador en la base local", 500)
    cuenta = Usuario(
        correo=usuario, nombre=nombre, hash_contrasena=hashear_contrasena(contrasena), roles=[rol]
    )
    sesion.add(cuenta)
    sesion.flush()
    codigo = _nuevo_codigo(sesion, cuenta)
    sesion.add(
        Auditoria(
            usuario_id=cuenta.id,
            accion="crear",
            entidad="usuario",
            entidad_id=str(cuenta.id),
            despues={"correo": usuario, "rol": "administrador", "origen": "primera_ejecucion"},
            ip=ip,
        )
    )
    sesion.commit()
    return codigo


def _intentos_recientes(sesion: Session, accion: str) -> int:
    return sesion.scalar(
        select(func.count())
        .select_from(Auditoria)
        .where(
            Auditoria.accion == accion,
            Auditoria.fecha >= datetime.now(UTC) - timedelta(minutes=MINUTOS_BLOQUEO),
        )
    )


def recuperar(sesion: Session, usuario: str, codigo: str, nueva: str, ip) -> str:
    """Pone una contraseña nueva con el código de recuperación. Devuelve el código nuevo."""
    # Una sola computadora: el límite es global (no por dirección).
    if _intentos_recientes(sesion, "recuperacion_fallida") >= LIMITE_INTENTOS:
        sesion.add(Auditoria(accion="recuperacion_limitada", entidad="usuario", ip=ip))
        sesion.commit()
        raise ErrorNegocio(f"Demasiados intentos; espera {MINUTOS_BLOQUEO} minutos", 429)
    validar_contrasena(nueva)
    correo = usuario.strip().lower()
    cuenta = sesion.scalar(select(Usuario).where(Usuario.correo == correo))
    huella = None
    if cuenta is not None and cuenta.activo:
        huella = sesion.scalar(
            select(cuenta_recuperacion.c.huella).where(
                cuenta_recuperacion.c.usuario_id == cuenta.id
            )
        )
    valido = verificar_contrasena(normalizar_codigo(codigo), huella or _HUELLA_FICTICIA)
    if not (valido and huella):
        sesion.add(
            Auditoria(
                accion="recuperacion_fallida",
                entidad="usuario",
                despues={"correo": correo},
                ip=ip,
            )
        )
        sesion.commit()
        raise ErrorNegocio("Usuario o código de recuperación incorrectos", 401)
    cuenta.hash_contrasena = hashear_contrasena(nueva)  # invalida las sesiones abiertas
    nuevo = _nuevo_codigo(sesion, cuenta)
    sesion.add(
        Auditoria(
            usuario_id=cuenta.id,
            accion="recuperar_contrasena",
            entidad="usuario",
            entidad_id=str(cuenta.id),
            despues={"origen": "codigo_de_recuperacion", "codigo_renovado": True},
            ip=ip,
        )
    )
    sesion.commit()
    return nuevo


def renovar_codigo(sesion: Session, cuenta: Usuario, contrasena: str, ip) -> str:
    """Genera un código nuevo (p. ej. si se perdió el kit). Pide la contraseña actual."""
    if not verificar_contrasena(contrasena, cuenta.hash_contrasena):
        sesion.add(
            Auditoria(
                usuario_id=cuenta.id,
                accion="contrasena_fallida",
                entidad="usuario",
                entidad_id=str(cuenta.id),
                ip=ip,
            )
        )
        sesion.commit()
        raise ErrorNegocio("La contraseña actual no es correcta", 401)
    codigo = _nuevo_codigo(sesion, cuenta)
    sesion.add(
        Auditoria(
            usuario_id=cuenta.id,
            accion="renovar_codigo_recuperacion",
            entidad="usuario",
            entidad_id=str(cuenta.id),
            ip=ip,
        )
    )
    sesion.commit()
    return codigo
