"""Utilidades compartidas por los servicios: errores, auditoría y normalización."""

import re
import unicodedata
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.models import Auditoria, Usuario


class ErrorNegocio(Exception):
    """Regla de negocio no cumplida. La API la convierte en una respuesta 4xx legible.

    `problemas` lista detalles (p. ej. cada traslape encontrado) para mostrarlos al usuario.
    """

    def __init__(self, mensaje: str, estado_http: int = 400, problemas: list[str] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.estado_http = estado_http
        self.problemas = problemas or []


class NoEncontrado(ErrorNegocio):
    def __init__(self, que: str):
        super().__init__(f"{que} no existe", 404)


def normalizar(texto: str) -> str:
    """'  José   de Jesús ' -> 'JOSE DE JESUS': sin acentos ni espacios extra, para comparar."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_acentos).strip().upper()


def normalizar_nombre_asignatura(texto: str) -> str:
    """'CÁLC. DIF.' y 'CALC DIF' son la misma asignatura: se ignoran signos de puntuación."""
    return re.sub(r"[^A-Z0-9]+", " ", normalizar(texto)).strip()


def _serializable(valor: Any) -> Any:
    if isinstance(valor, date | datetime | time):
        return valor.isoformat()
    if isinstance(valor, list):
        return [_serializable(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    return valor


def instantanea(objeto: Any, campos: list[str]) -> dict[str, Any]:
    """Copia de los campos indicados, lista para guardarse en la auditoría (JSON)."""
    return {c: _serializable(getattr(objeto, c)) for c in campos}


def auditar(
    sesion: Session,
    usuario: Usuario | None,
    accion: str,
    entidad: str,
    entidad_id: int | str | None,
    antes: dict | None = None,
    despues: dict | None = None,
) -> None:
    sesion.add(
        Auditoria(
            usuario_id=usuario.id if usuario else None,
            accion=accion,
            entidad=entidad,
            entidad_id=str(entidad_id) if entidad_id is not None else None,
            antes=_serializable(antes) if antes is not None else None,
            despues=_serializable(despues) if despues is not None else None,
        )
    )
