"""Calendario institucional: días inhábiles, vacaciones, suspensiones y excepciones.

Un evento puede abarcar varios días y aplicar a todo el día o a un solo turno.
Prioridad: una excepción "hábil" gana sobre un inhábil, unas vacaciones o una suspensión
(p. ej. se repone una clase en día festivo con autorización).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import EventoCalendario, Usuario
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, instantanea

CAMPOS = ["tipo", "fecha_inicio", "fecha_fin", "turno", "descripcion", "activo"]
NOMBRES = {
    "inhabil": "Día inhábil",
    "vacaciones": "Vacaciones",
    "suspension": "Suspensión",
    "habil": "Día hábil por excepción",
}


@dataclass
class EstadoDia:
    habil: bool
    motivo: str = ""  # por qué es inhábil, o la excepción que lo vuelve hábil


def listar(
    sesion: Session,
    desde: date | None = None,
    hasta: date | None = None,
    incluir_anulados: bool = False,
) -> list[EventoCalendario]:
    consulta = select(EventoCalendario).order_by(EventoCalendario.fecha_inicio)
    if desde:
        consulta = consulta.where(EventoCalendario.fecha_fin >= desde)
    if hasta:
        consulta = consulta.where(EventoCalendario.fecha_inicio <= hasta)
    if not incluir_anulados:
        consulta = consulta.where(EventoCalendario.activo)
    return list(sesion.scalars(consulta))


def obtener(sesion: Session, id_: int) -> EventoCalendario:
    evento = sesion.get(EventoCalendario, id_)
    if evento is None:
        raise NoEncontrado("El evento del calendario")
    return evento


def _validar(datos: dict) -> None:
    if datos["fecha_fin"] < datos["fecha_inicio"]:
        raise ErrorNegocio("La fecha final no puede ser anterior a la inicial", 422)
    if (datos["fecha_fin"] - datos["fecha_inicio"]).days > 366:
        raise ErrorNegocio("Un evento no puede durar más de un año", 422)
    if not (datos.get("descripcion") or "").strip():
        raise ErrorNegocio("Describe el motivo del evento", 422)


def crear(sesion: Session, usuario: Usuario, datos: dict) -> EventoCalendario:
    _validar(datos)
    evento = EventoCalendario(**datos, creado_por_id=usuario.id)
    evento.descripcion = evento.descripcion.strip()
    sesion.add(evento)
    sesion.flush()
    auditar(sesion, usuario, "crear", "calendario", evento.id, despues=instantanea(evento, CAMPOS))
    sesion.commit()
    return evento


def editar(sesion: Session, usuario: Usuario, id_: int, cambios: dict) -> EventoCalendario:
    evento = obtener(sesion, id_)
    antes = instantanea(evento, CAMPOS)
    datos = {**antes, **cambios}
    datos["fecha_inicio"] = date.fromisoformat(str(datos["fecha_inicio"]))
    datos["fecha_fin"] = date.fromisoformat(str(datos["fecha_fin"]))
    _validar(datos)
    for clave, valor in cambios.items():
        setattr(evento, clave, valor)
    despues = instantanea(evento, CAMPOS)
    if despues != antes:
        accion = "anular" if antes["activo"] and not evento.activo else "editar"
        auditar(sesion, usuario, accion, "calendario", evento.id, antes, despues)
    sesion.commit()
    return evento


def estado_dia(sesion: Session, fecha: date, turno: str | None = None) -> EstadoDia:
    """¿Es hábil esta fecha (y turno)? Domingo nunca es hábil."""
    eventos = sesion.scalars(
        select(EventoCalendario).where(
            EventoCalendario.activo,
            EventoCalendario.fecha_inicio <= fecha,
            EventoCalendario.fecha_fin >= fecha,
            or_(EventoCalendario.turno.is_(None), EventoCalendario.turno == turno)
            if turno
            else EventoCalendario.turno.is_(None),
        )
    ).all()
    excepcion = next((e for e in eventos if e.tipo == "habil"), None)
    if excepcion is not None:
        return EstadoDia(True, f"{NOMBRES['habil']}: {excepcion.descripcion}")
    if fecha.weekday() == 6:
        return EstadoDia(False, "Domingo")
    inhabil = next((e for e in eventos if e.tipo != "habil"), None)
    if inhabil is not None:
        return EstadoDia(False, f"{NOMBRES[inhabil.tipo]}: {inhabil.descripcion}")
    return EstadoDia(True)
