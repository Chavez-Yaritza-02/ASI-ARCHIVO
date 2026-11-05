"""Punto de entrada de la API.

Ejecutar en desarrollo:  uv run uvicorn app.main:app --reload --app-dir server
Documentación interactiva: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import (
    asistencia_hora,
    auth,
    bitacora,
    catalogos,
    consultas,
    documentos,
    horarios,
    importaciones,
    periodos,
    sistema,
)
from app.archivos.limites import LimiteArchivoMiddleware
from app.core.accesos import registrar_acceso
from app.core.config import obtener_configuracion
from app.services.comun import ErrorNegocio
from asi_shared.version import VERSION

app = FastAPI(title="ASI-ARCHIVO API", version=VERSION)
app.middleware("http")(registrar_acceso)
if obtener_configuracion().hosts_permitidos:
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=obtener_configuracion().hosts_permitidos
    )
app.include_router(sistema.router)

app.add_middleware(LimiteArchivoMiddleware)
app.include_router(documentos.router)
app.include_router(auth.router)
app.include_router(asistencia_hora.router)
app.include_router(consultas.router)
app.include_router(catalogos.docentes)
app.include_router(catalogos.asignaturas)
app.include_router(catalogos.grupos)
app.include_router(catalogos.aulas)
app.include_router(periodos.router)
app.include_router(horarios.router)
app.include_router(importaciones.router)
app.include_router(bitacora.bitacora)
app.include_router(bitacora.asistencias)
app.include_router(bitacora.incidencias)
app.include_router(bitacora.calendario)


@app.exception_handler(ErrorNegocio)
def _error_negocio(_: Request, error: ErrorNegocio) -> JSONResponse:
    return JSONResponse(
        status_code=error.estado_http,
        content={"detail": error.mensaje, "problemas": error.problemas},
    )


@app.exception_handler(IntegrityError)
def _error_integridad(_: Request, __: IntegrityError) -> JSONResponse:
    # Respaldo: las reglas de negocio validan antes, pero si dos personas guardan a la
    # vez, la base de datos sigue impidiendo duplicados (p. ej. dos versiones vigentes).
    return JSONResponse(
        status_code=409,
        content={"detail": "El cambio choca con datos existentes; actualiza e intenta de nuevo"},
    )


@app.exception_handler(OperationalError)
def _datos_no_disponibles(_: Request, __: OperationalError):
    return JSONResponse(
        status_code=503, content={"detail": "El servicio de datos no está disponible"}
    )


@app.get("/salud", tags=["sistema"])
def salud() -> dict[str, str]:
    """Permite al cliente comprobar que el servidor responde."""
    return {"estado": "ok"}
