"""Diagnóstico sin credenciales ni rutas internas; no inicializa ni migra datos."""

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SesionDB, UsuarioActual
from app.core.config import obtener_configuracion
from asi_shared.version import PROTOCOLO, VERSION

router = APIRouter(prefix="/sistema", tags=["sistema"])


@router.get("/identidad")
def identidad():
    return {
        "producto": "ASI-ARCHIVO",
        "version": VERSION,
        "protocolo": PROTOCOLO,
        "aceptacion_ficticia": obtener_configuracion().instancia_aceptacion,
        # Para que la aplicación muestre siempre a qué servidor está conectada.
        "entorno": obtener_configuracion().entorno,
        "tipo_servidor": obtener_configuracion().tipo_servidor,
    }


@router.get("/estado")
def estado(sesion: SesionDB, _: UsuarioActual, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        sesion.execute(text("SELECT 1"))
        revision = sesion.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    except SQLAlchemyError as error:
        raise HTTPException(503, "El servicio de datos no está disponible") from error
    if revision != ["e6a001"]:
        raise HTTPException(503, "El esquema requiere revisión del administrador")
    c = obtener_configuracion()
    return {
        **identidad(),
        "estado": "ok",
        "base_de_datos": "ok",
        "esquema": "compatible",
        "antivirus_configurado": bool(
            c.archivo_antivirus_cmd and c.archivo_antivirus_cmd.is_file()
        ),
        "almacen_existente": c.archivo_raiz.is_dir(),
    }
