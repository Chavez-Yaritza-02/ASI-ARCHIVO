"""Comparación de lo leído por el OCR con los catálogos (aulas, asignaturas, docentes).

Regla: nunca asignar una coincidencia dudosa de forma automática.
- coincide: el texto normalizado es idéntico a un único registro. Se asigna.
- sugerido: se parece a un único registro (confusiones típicas del OCR, como
  "MOS" por "M05", o 1–2 letras distintas). Se propone, pero el usuario lo acepta.
- sin_coincidencia: no se parece a nada, o se parece a varios (ambiguo). El usuario elige.
"""

from dataclasses import dataclass, field

from app.importers.analisis import (
    esqueleto,
    igual_o_un_caracter_extra,
    normalizar,
    numeral_final,
    similitud,
)
from app.services.comun import normalizar_nombre_asignatura

COINCIDE, SUGERIDO, SIN_COINCIDENCIA, VACIO = "coincide", "sugerido", "sin_coincidencia", "vacio"
UMBRAL_NOMBRE = 0.9


@dataclass
class Resultado:
    id: int | None
    estado: str
    candidatos: list[int] = field(default_factory=list)  # si es ambiguo


def _unico(candidatos: list[int], estado: str) -> Resultado | None:
    if len(candidatos) == 1:
        return Resultado(candidatos[0], estado)
    if len(candidatos) > 1:
        return Resultado(None, SIN_COINCIDENCIA, candidatos)
    return None


def buscar_aula(texto: str | None, aulas: list[tuple[int, str]]) -> Resultado:
    """`aulas`: (id, clave) de las aulas activas."""
    if not texto or not texto.strip():
        return Resultado(None, VACIO)
    plano = normalizar(texto).replace(" ", "")
    exactas = [i for i, c in aulas if normalizar(c).replace(" ", "") == plano]
    if r := _unico(exactas, COINCIDE):
        return r
    parecidas = [i for i, c in aulas if esqueleto(c) == esqueleto(texto)]
    if r := _unico(parecidas, SUGERIDO):
        return r
    extra = [i for i, c in aulas if igual_o_un_caracter_extra(esqueleto(c), esqueleto(texto))]
    return _unico(extra, SUGERIDO) or Resultado(None, SIN_COINCIDENCIA)


def buscar_asignatura(texto: str, asignaturas: list[tuple[int, str]]) -> Resultado:
    """`asignaturas`: (id, nombre) de las asignaturas activas."""
    if not texto or not texto.strip():
        return Resultado(None, SIN_COINCIDENCIA)
    plano = normalizar_nombre_asignatura(texto)
    exactas = [i for i, n in asignaturas if normalizar_nombre_asignatura(n) == plano]
    if r := _unico(exactas, COINCIDE):
        return r
    # Parecida y con el mismo numeral final: "Avan I" nunca se confunde con "Avan II".
    parecidas = [
        i
        for i, n in asignaturas
        if similitud(n, texto) >= UMBRAL_NOMBRE and numeral_final(n) == numeral_final(texto)
    ]
    return _unico(parecidas, SUGERIDO) or Resultado(None, SIN_COINCIDENCIA)


def buscar_docente(
    nombre: str, nomina: str | None, docentes: list[tuple[int, str, str | None]]
) -> Resultado:
    """`docentes`: (id, nombre, nómina) de los docentes activos."""
    if nomina:
        por_nomina = [i for i, _, n in docentes if n and n.upper() == nomina.upper()]
        if r := _unico(por_nomina, COINCIDE):
            return r
    if not nombre or not nombre.strip():
        return Resultado(None, SIN_COINCIDENCIA)
    plano = normalizar(nombre)
    exactos = [i for i, n, _ in docentes if normalizar(n) == plano]
    if r := _unico(exactos, COINCIDE):
        return r
    parecidos = [i for i, n, _ in docentes if similitud(n, nombre) >= UMBRAL_NOMBRE]
    return _unico(parecidos, SUGERIDO) or Resultado(None, SIN_COINCIDENCIA)
