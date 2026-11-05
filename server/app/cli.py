r"""Comandos de administración de usuarios.

Las contraseñas se piden en pantalla (o se leen de la entrada estándar con
--contrasena-stdin); nunca se escriben en la línea de comandos ni en el código.

En el servidor (ver docs/MANUAL_ADMINISTRADOR.md):
    ./admin.sh listar-usuarios
    ./admin.sh crear-usuario --correo persona@tecmm.edu.mx --nombre "Nombre" --rol consulta
    ./admin.sh restablecer-contrasena --correo persona@tecmm.edu.mx
    ./admin.sh desactivar-usuario --correo persona@tecmm.edu.mx
    ./admin.sh activar-usuario --correo persona@tecmm.edu.mx
    ./admin.sh cambiar-rol --correo persona@tecmm.edu.mx --rol administrador
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.seguridad import hashear_contrasena
from app.db.proteccion_pruebas import en_pruebas, validar_conexion_pruebas
from app.db.sesion import obtener_engine
from app.models import Auditoria, Rol, Usuario

LONGITUD_MINIMA = 10


def crear_usuario(sesion: Session, correo: str, nombre: str, rol: str, contrasena: str) -> Usuario:
    if en_pruebas():
        validar_conexion_pruebas(sesion.connection())
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


def _buscar(sesion: Session, correo: str) -> Usuario:
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo.strip().lower()))
    if usuario is None:
        raise ValueError(f"No existe un usuario con el correo {correo}")
    return usuario


def _auditar(sesion: Session, usuario: Usuario, accion: str, antes: dict, despues: dict) -> None:
    # Acciones de consola: no hay usuario de la aplicación que las haga (usuario_id vacío).
    sesion.add(
        Auditoria(
            accion=accion,
            entidad="usuario",
            entidad_id=str(usuario.id),
            antes=antes,
            despues={**despues, "origen": "consola"},
        )
    )


def listar_usuarios(sesion: Session) -> list[Usuario]:
    if en_pruebas():
        validar_conexion_pruebas(sesion.connection())
    return list(sesion.scalars(select(Usuario).order_by(Usuario.correo)))


def restablecer_contrasena(sesion: Session, correo: str, contrasena: str) -> Usuario:
    if en_pruebas():
        validar_conexion_pruebas(sesion.connection())
    if len(contrasena) < LONGITUD_MINIMA:
        raise ValueError(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres")
    usuario = _buscar(sesion, correo)
    usuario.hash_contrasena = hashear_contrasena(contrasena)
    _auditar(sesion, usuario, "restablecer_contrasena", {}, {"correo": usuario.correo})
    sesion.commit()
    return usuario


def cambiar_estado(sesion: Session, correo: str, activo: bool) -> Usuario:
    """Desactivar impide iniciar sesión de inmediato (también con sesiones abiertas)."""
    if en_pruebas():
        validar_conexion_pruebas(sesion.connection())
    usuario = _buscar(sesion, correo)
    if usuario.activo != activo:
        _auditar(
            sesion,
            usuario,
            "activar" if activo else "desactivar",
            {"activo": usuario.activo},
            {"activo": activo},
        )
        usuario.activo = activo
    sesion.commit()
    return usuario


def cambiar_rol(sesion: Session, correo: str, rol: str) -> Usuario:
    if en_pruebas():
        validar_conexion_pruebas(sesion.connection())
    usuario = _buscar(sesion, correo)
    rol_db = sesion.scalar(select(Rol).where(Rol.nombre == rol))
    if rol_db is None:
        raise ValueError(f"El rol '{rol}' no existe")
    antes = sorted(r.nombre for r in usuario.roles)
    usuario.roles = [rol_db]
    _auditar(sesion, usuario, "cambiar_rol", {"roles": antes}, {"roles": [rol]})
    sesion.commit()
    return usuario


def _leer_contrasena(desde_stdin: bool) -> str:
    if desde_stdin:
        return sys.stdin.readline().rstrip("\n")
    contrasena = getpass.getpass("Contraseña nueva: ")
    if contrasena != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden")
    return contrasena


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Administración de usuarios")
    sub = parser.add_subparsers(dest="comando", required=True)
    roles = ["administrador", "consulta"]

    crear = sub.add_parser("crear-usuario", help="Crea un usuario nuevo")
    crear.add_argument("--correo", required=True)
    crear.add_argument("--nombre", required=True)
    crear.add_argument("--rol", default="consulta", choices=roles)
    crear.add_argument(
        "--contrasena-stdin",
        action="store_true",
        help="Lee la contraseña de la entrada estándar (para scripts)",
    )
    sub.add_parser("listar-usuarios", help="Muestra los usuarios, su rol y si están activos")
    restablecer = sub.add_parser("restablecer-contrasena", help="Asigna una contraseña nueva")
    restablecer.add_argument("--correo", required=True)
    restablecer.add_argument("--contrasena-stdin", action="store_true")
    for nombre, ayuda in (
        ("desactivar-usuario", "Impide que el usuario inicie sesión"),
        ("activar-usuario", "Permite de nuevo el acceso"),
    ):
        sub.add_parser(nombre, help=ayuda).add_argument("--correo", required=True)
    rol = sub.add_parser("cambiar-rol", help="Cambia el rol de un usuario")
    rol.add_argument("--correo", required=True)
    rol.add_argument("--rol", required=True, choices=roles)
    args = parser.parse_args()

    with Session(obtener_engine()) as sesion:
        try:
            if args.comando == "crear-usuario":
                contrasena = _leer_contrasena(args.contrasena_stdin)
                u = crear_usuario(sesion, args.correo, args.nombre, args.rol, contrasena)
                print(f"Usuario creado: {u.correo} ({args.rol})")
            elif args.comando == "listar-usuarios":
                for u in listar_usuarios(sesion):
                    estado = "activo" if u.activo else "DESACTIVADO"
                    roles_u = ", ".join(r.nombre for r in u.roles)
                    print(f"{u.correo:40} {u.nombre:30} {roles_u:15} {estado}")
            elif args.comando == "restablecer-contrasena":
                contrasena = _leer_contrasena(args.contrasena_stdin)
                u = restablecer_contrasena(sesion, args.correo, contrasena)
                print(f"Contraseña restablecida para {u.correo}")
            elif args.comando in ("desactivar-usuario", "activar-usuario"):
                activo = args.comando == "activar-usuario"
                u = cambiar_estado(sesion, args.correo, activo)
                print(f"{u.correo}: {'activo' if activo else 'desactivado'}")
            elif args.comando == "cambiar-rol":
                u = cambiar_rol(sesion, args.correo, args.rol)
                print(f"{u.correo}: rol {args.rol}")
        except ValueError as error:
            sys.exit(f"Error: {error}")


if __name__ == "__main__":
    main()
