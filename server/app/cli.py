r"""Comandos de administración.

Crear un usuario (la contraseña se pide en pantalla, nunca va en el código):
    cd server
    uv run python -m app.cli crear-usuario --correo tu@correo.mx \
        --nombre "Tu Nombre" --rol administrador
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.seguridad import hashear_contrasena
from app.db.sesion import obtener_engine
from app.models import Auditoria, Rol, Usuario

LONGITUD_MINIMA = 10


def crear_usuario(sesion: Session, correo: str, nombre: str, rol: str, contrasena: str) -> Usuario:
    correo = correo.strip().lower()
    if len(contrasena) < LONGITUD_MINIMA:
        raise ValueError(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres")
    if sesion.scalar(select(Usuario).where(Usuario.correo == correo)):
        raise ValueError(f"Ya existe un usuario con el correo {correo}")
    rol_db = sesion.scalar(select(Rol).where(Rol.nombre == rol))
    if rol_db is None:
        raise ValueError(f"El rol '{rol}' no existe")

    usuario = Usuario(
        correo=correo, nombre=nombre, hash_contrasena=hashear_contrasena(contrasena), roles=[rol_db]
    )
    sesion.add(usuario)
    sesion.flush()
    sesion.add(
        Auditoria(
            accion="crear",
            entidad="usuario",
            entidad_id=str(usuario.id),
            despues={"correo": correo, "rol": rol},
        )
    )
    sesion.commit()
    return usuario


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    crear = sub.add_parser("crear-usuario", help="Crea un usuario nuevo")
    crear.add_argument("--correo", required=True)
    crear.add_argument("--nombre", required=True)
    crear.add_argument("--rol", default="consulta", choices=["administrador", "consulta"])
    args = parser.parse_args()

    contrasena = getpass.getpass("Contraseña: ")
    if contrasena != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden")

    with Session(obtener_engine()) as sesion:
        try:
            usuario = crear_usuario(sesion, args.correo, args.nombre, args.rol, contrasena)
        except ValueError as error:
            sys.exit(f"Error: {error}")
    print(f"Usuario creado: {usuario.correo} ({args.rol})")


if __name__ == "__main__":
    main()
