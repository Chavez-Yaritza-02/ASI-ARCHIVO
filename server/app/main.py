"""Punto de entrada de la API.

Ejecutar en desarrollo:  uv run uvicorn app.main:app --reload --app-dir server
Documentación interactiva: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from app.api import auth

app = FastAPI(title="ASI-ARCHIVO API", version="0.1.0")
app.include_router(auth.router)


@app.get("/salud", tags=["sistema"])
def salud() -> dict[str, str]:
    """Permite al cliente comprobar que el servidor responde."""
    return {"estado": "ok"}
