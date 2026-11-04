"""Reglas de negocio de docentes y catálogos (asignaturas, grupos, aulas)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asignatura, Aula, Docente, Grupo, Periodo, Usuario
from app.services.comun import (
    ErrorNegocio,
    NoEncontrado,
    auditar,
    instantanea,
    normalizar,
    normalizar_nombre_asignatura,
)

# Cómo se identifica cada catálogo y qué campo no puede repetirse.
CATALOGOS: dict[str, dict[str, Any]] = {
    "docente": {
        "modelo": Docente,
        "titulo": "El docente",
        "campos": ["nombre", "nomina", "correo", "activo"],
        "unico": ("nombre_normalizado", lambda d: normalizar(d["nombre"])),
    },
    "asignatura": {
        "modelo": Asignatura,
        "titulo": "La asignatura",
        "campos": ["nombre", "tipo", "activo"],
        "unico": ("nombre_normalizado", lambda d: normalizar_nombre_asignatura(d["nombre"])),
    },
    "grupo": {
        "modelo": Grupo,
        "titulo": "El grupo",
        "campos": ["periodo_id", "carrera", "semestre", "letra", "clave", "descripcion", "activo"],
        "unico": ("llave", lambda d: llave_grupo(d)),
    },
    "aula": {
        "modelo": Aula,
        "titulo": "El aula",
        "campos": ["clave", "descripcion", "activo"],
        "unico": ("clave", lambda d: normalizar(d["clave"])),
    },
}


def llave_grupo(datos: dict) -> str:
    """Identidad de un grupo: periodo|carrera|semestre|letra ('-' si falta el dato)."""
    partes = [datos.get("periodo_id"), datos.get("carrera"), datos.get("semestre")]
    return "|".join("-" if p in (None, "") else str(p) for p in partes) + f"|{datos['letra']}"


def clave_grupo(datos: dict) -> str:
    """Texto para mostrar: 'IEM 3A' si el grupo está completo, solo 'A' si está pendiente."""
    if datos.get("carrera") and datos.get("semestre"):
        return f"{datos['carrera']} {datos['semestre']}{datos['letra']}"
    return datos["letra"]


def obtener(sesion: Session, entidad: str, id_: int):
    cfg = CATALOGOS[entidad]
    objeto = sesion.get(cfg["modelo"], id_)
    if objeto is None:
        raise NoEncontrado(cfg["titulo"])
    return objeto


def listar(
    sesion: Session,
    entidad: str,
    buscar: str = "",
    activo: bool | None = None,
    periodo_id: int | None = None,
):
    cfg = CATALOGOS[entidad]
    modelo = cfg["modelo"]
    columna_unica = getattr(modelo, "clave" if entidad == "grupo" else cfg["unico"][0])
    consulta = select(modelo).order_by(columna_unica)
    if buscar:
        texto = (
            normalizar_nombre_asignatura(buscar) if entidad == "asignatura" else normalizar(buscar)
        )
        consulta = consulta.where(columna_unica.contains(texto))
    if entidad == "grupo" and periodo_id is not None:
        consulta = consulta.where(modelo.periodo_id == periodo_id)
    if activo is not None:
        consulta = consulta.where(modelo.activo == activo)
    return list(sesion.scalars(consulta))


def _verificar_unicos(sesion: Session, entidad: str, datos: dict, excluir_id: int | None) -> None:
    cfg = CATALOGOS[entidad]
    modelo = cfg["modelo"]
    campo, calcular = cfg["unico"]
    if entidad == "grupo" and not datos.get("letra"):
        raise ErrorNegocio("El grupo necesita letra")
    valor = calcular(datos)
    if not valor:
        raise ErrorNegocio(f"{cfg['titulo']} necesita {'nombre' if 'nombre' in datos else 'clave'}")
    existente = sesion.scalar(select(modelo).where(getattr(modelo, campo) == valor))
    if existente is not None and existente.id != excluir_id:
        raise ErrorNegocio(f"{cfg['titulo']} ya existe (registro {existente.id})", 409)
    if entidad == "docente" and datos.get("nomina"):
        otro = sesion.scalar(select(Docente).where(Docente.nomina == datos["nomina"]))
        if otro is not None and otro.id != excluir_id:
            raise ErrorNegocio(f"La nómina {datos['nomina']} ya pertenece a otro docente", 409)


def _limpiar(entidad: str, datos: dict) -> dict:
    datos = {k: (v.strip() if isinstance(v, str) else v) for k, v in datos.items()}
    if entidad == "docente":
        # Se conservan los acentos para mostrarlo; la búsqueda usa nombre_normalizado.
        datos["nombre"] = " ".join((datos.get("nombre") or "").split()).upper()
        datos["nomina"] = datos.get("nomina") or None
        datos["correo"] = (datos.get("correo") or "").lower() or None
    if entidad == "asignatura":
        datos["nombre"] = " ".join((datos.get("nombre") or "").split())
    if entidad == "aula" and datos.get("clave"):
        datos["clave"] = normalizar(datos["clave"])
    if entidad == "grupo":
        datos["letra"] = normalizar(datos.get("letra") or "").replace(" ", "")
        datos["carrera"] = normalizar(datos["carrera"]) if datos.get("carrera") else None
        datos["clave"] = clave_grupo(datos) if datos["letra"] else ""
    return datos


def _verificar_periodo(sesion: Session, entidad: str, datos: dict) -> None:
    periodo_id = datos.get("periodo_id") if entidad == "grupo" else None
    if periodo_id is not None and sesion.get(Periodo, periodo_id) is None:
        raise NoEncontrado("El periodo")


def crear(sesion: Session, usuario: Usuario, entidad: str, datos: dict):
    cfg = CATALOGOS[entidad]
    datos = _limpiar(entidad, datos)
    _verificar_periodo(sesion, entidad, datos)
    _verificar_unicos(sesion, entidad, datos, excluir_id=None)
    objeto = cfg["modelo"](**datos)
    campo, calcular = cfg["unico"]
    setattr(objeto, campo, calcular(datos))
    sesion.add(objeto)
    sesion.flush()
    auditar(
        sesion, usuario, "crear", entidad, objeto.id, despues=instantanea(objeto, cfg["campos"])
    )
    sesion.commit()
    return objeto


def editar(sesion: Session, usuario: Usuario, entidad: str, id_: int, cambios: dict):
    cfg = CATALOGOS[entidad]
    objeto = obtener(sesion, entidad, id_)
    antes = instantanea(objeto, cfg["campos"])
    datos = _limpiar(entidad, {**antes, **cambios})
    _verificar_periodo(sesion, entidad, datos)
    _verificar_unicos(sesion, entidad, datos, excluir_id=objeto.id)
    for clave, valor in datos.items():
        setattr(objeto, clave, valor)
    campo, calcular = cfg["unico"]
    setattr(objeto, campo, calcular(datos))
    despues = instantanea(objeto, cfg["campos"])
    if despues != antes:
        accion = "editar"
        if antes["activo"] != despues["activo"]:
            accion = "activar" if despues["activo"] else "desactivar"
        auditar(sesion, usuario, accion, entidad, objeto.id, antes=antes, despues=despues)
    sesion.commit()
    return objeto
