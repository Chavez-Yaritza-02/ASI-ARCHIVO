"""Reglas de negocio de los periodos académicos.

    borrador --(activar)--> activo --(cerrar)--> cerrado

Solo un periodo puede estar activo. Para activar uno nuevo primero se cierra el
anterior, de forma explícita: así nadie cambia de semestre por accidente. Los
periodos cerrados quedan de solo lectura (sus horarios se conservan como historial).
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Periodo, Usuario
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, instantanea

CAMPOS = ["nombre", "fecha_inicio", "fecha_fin", "estado"]


def obtener(sesion: Session, id_: int) -> Periodo:
    periodo = sesion.get(Periodo, id_)
    if periodo is None:
        raise NoEncontrado("El periodo")
    return periodo


def listar(sesion: Session) -> list[Periodo]:
    return list(sesion.scalars(select(Periodo).order_by(Periodo.fecha_inicio.desc())))


def activo(sesion: Session) -> Periodo | None:
    return sesion.scalar(select(Periodo).where(Periodo.estado == "activo"))


def _validar(sesion: Session, nombre: str, inicio: date, fin: date, excluir_id: int | None):
    if not nombre.strip():
        raise ErrorNegocio("El periodo necesita un nombre")
    if fin <= inicio:
        raise ErrorNegocio("La fecha de fin debe ser posterior a la de inicio")
    for otro in listar(sesion):
        if otro.id == excluir_id:
            continue
        if otro.nombre.upper() == nombre.strip().upper():
            raise ErrorNegocio(f"Ya existe un periodo llamado {otro.nombre}", 409)
        if inicio <= otro.fecha_fin and otro.fecha_inicio <= fin:
            raise ErrorNegocio(
                f"Las fechas se traslapan con el periodo {otro.nombre} "
                f"({otro.fecha_inicio} a {otro.fecha_fin})",
                409,
            )


def crear(sesion: Session, usuario: Usuario, nombre: str, inicio: date, fin: date) -> Periodo:
    _validar(sesion, nombre, inicio, fin, excluir_id=None)
    periodo = Periodo(nombre=nombre.strip().upper(), fecha_inicio=inicio, fecha_fin=fin)
    periodo.estado = "borrador"
    sesion.add(periodo)
    sesion.flush()
    auditar(sesion, usuario, "crear", "periodo", periodo.id, despues=instantanea(periodo, CAMPOS))
    sesion.commit()
    return periodo


def editar(
    sesion: Session, usuario: Usuario, id_: int, nombre: str, inicio: date, fin: date
) -> Periodo:
    periodo = obtener(sesion, id_)
    if periodo.estado == "cerrado":
        raise ErrorNegocio("Un periodo cerrado no se puede modificar", 409)
    antes = instantanea(periodo, CAMPOS)
    _validar(sesion, nombre, inicio, fin, excluir_id=periodo.id)
    periodo.nombre, periodo.fecha_inicio, periodo.fecha_fin = nombre.strip().upper(), inicio, fin
    auditar(sesion, usuario, "editar", "periodo", periodo.id, antes, instantanea(periodo, CAMPOS))
    sesion.commit()
    return periodo


def activar(sesion: Session, usuario: Usuario, id_: int) -> Periodo:
    periodo = obtener(sesion, id_)
    if periodo.estado != "borrador":
        raise ErrorNegocio(
            f"Solo se puede activar un periodo en borrador (está {periodo.estado})", 409
        )
    actual = activo(sesion)
    if actual is not None:
        raise ErrorNegocio(f"Primero cierra el periodo activo: {actual.nombre}", 409)
    antes = instantanea(periodo, CAMPOS)
    periodo.estado = "activo"
    auditar(sesion, usuario, "activar", "periodo", periodo.id, antes, instantanea(periodo, CAMPOS))
    sesion.commit()
    return periodo


def cerrar(sesion: Session, usuario: Usuario, id_: int) -> Periodo:
    periodo = obtener(sesion, id_)
    if periodo.estado == "cerrado":
        raise ErrorNegocio("El periodo ya está cerrado", 409)
    antes = instantanea(periodo, CAMPOS)
    periodo.estado = "cerrado"
    auditar(sesion, usuario, "cerrar", "periodo", periodo.id, antes, instantanea(periodo, CAMPOS))
    sesion.commit()
    return periodo
