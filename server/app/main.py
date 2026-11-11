"""Punto de entrada de la API.

Ejecutar en desarrollo:  uv run uvicorn app.main:app --reload --app-dir server
Documentación interactiva: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import auth, catalogos, horarios, periodos
from app.services.comun import ErrorNegocio

app = FastAPI(title="ASI-ARCHIVO API", version="0.2.0")
app.include_router(auth.router)
app.include_router(catalogos.docentes)
app.include_router(catalogos.asignaturas)
app.include_router(catalogos.grupos)
app.include_router(catalogos.aulas)
app.include_router(periodos.router)
app.include_router(horarios.router)


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


@app.get("/salud", tags=["sistema"])
def salud() -> dict[str, str]:
    """Permite al cliente comprobar que el servidor responde."""
    return {"estado": "ok"}
