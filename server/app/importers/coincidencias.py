"""Comparación de lo leído por el OCR con los catálogos (aulas, asignaturas, docentes).

Regla: nunca asignar una coincidencia dudosa de forma automática.
- coincide: el texto normalizado es idéntico a un único registro. Se asigna.
- sugerido: se parece a un único registro (confusiones típicas del OCR, como
  "MOS" por "M05" o "ELFCT" por "ELECT", 1–2 letras distintas, o una abreviatura
  habitual como "PROP. MAT." por "Propiedades de los Materiales"). Se propone, pero el
  usuario lo acepta.
- sin_coincidencia: no se parece a nada, o se parece a varios (ambiguo). El usuario elige.
"""

import re
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


# Letras que el OCR confunde en esta tipografía: cambiar una por otra cuesta media edición.
_PARECIDAS = {
    frozenset(par)
    for par in ("EF", "EB", "OQ", "O0", "OD", "I1", "IL", "L1", "S5", "B8", "Z2", "G6", "CG")
}
# Abreviaturas habituales en los horarios que no son el inicio de la palabra completa.
ABREVIATURAS = {
    "ADMON": "ADMINISTRACION",
    "MTTO": "MANTENIMIENTO",
    "MANTTO": "MANTENIMIENTO",
    "GRAL": "GENERAL",
    "DEPTO": "DEPARTAMENTO",
    "EDO": "ESTADO",
}
_VACIAS = {"DE", "DEL", "LA", "LAS", "EL", "LOS", "Y", "E", "EN", "A", "AL", "PARA"}
_NUMERAL = re.compile(r"^(?:[IVX]+|\d+)$")


def distancia_ocr(a: str, b: str) -> float:
    """Distancia de edición en la que las confusiones típicas del OCR cuestan 0.5."""
    previa = [float(j) for j in range(len(b) + 1)]
    for i, ca in enumerate(a, 1):
        actual = [float(i)]
        for j, cb in enumerate(b, 1):
            cambio = 0.0 if ca == cb else (0.5 if frozenset((ca, cb)) in _PARECIDAS else 1.0)
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + cambio))
        previa = actual
    return previa[-1]


def _compacto(texto: str) -> str:
    """Sin mayúsculas/minúsculas, acentos, espacios ni signos: 'Sub. Eléct.' -> 'SUBELECT'."""
    return normalizar_nombre_asignatura(texto).replace(" ", "")


def _tolerancia(compacto: str) -> float:
    return 1.0 if len(compacto) <= 5 else 2.0  # textos cortos: a lo más una letra


def _palabras(texto: str) -> list[str]:
    return [
        ABREVIATURAS.get(p, p)
        for p in normalizar_nombre_asignatura(texto).split()
        if p not in _VACIAS
    ]


def _palabra_abreviada(corta: str, larga: str) -> bool:
    if corta == larga:
        return True
    if _NUMERAL.match(corta) or _NUMERAL.match(larga) or len(corta) < 3:
        return False  # los numerales y las siglas de 1–2 letras deben ser idénticos
    inicio = larga[: len(corta)]
    return inicio == corta or (len(corta) >= 4 and distancia_ocr(corta, inicio) <= 1)


def es_abreviatura(texto: str, nombre: str) -> bool:
    """'PROP. MAT.' ~ 'Propiedades de los Materiales': cada palabra es el inicio de la otra."""
    a, b = _palabras(texto), _palabras(nombre)
    if not a or len(a) != len(b) or len(_compacto(texto)) < 4:
        return False  # «TOR» es demasiado corto para proponer una materia
    return all(_palabra_abreviada(*sorted((x, y), key=len)) for x, y in zip(a, b, strict=True))


def _cercana(texto: str, nombre: str) -> bool:
    if numeral_final(nombre) != numeral_final(texto):
        return False  # "Avan I" nunca se confunde con "Avan II"
    a, b = _compacto(texto), _compacto(nombre)
    if distancia_ocr(a, b) <= min(_tolerancia(a), _tolerancia(b)):
        return True
    return similitud(nombre, texto) >= UMBRAL_NOMBRE


def buscar_asignatura(texto: str, asignaturas: list[tuple[int, str]]) -> Resultado:
    """`asignaturas`: (id, nombre) de las asignaturas activas.

    Por niveles; en cuanto un nivel encuentra algo se detiene. Si hay más de un parecido
    en el mismo nivel es ambiguo y no se propone ninguno.
    """
    if not texto or not texto.strip():
        return Resultado(None, SIN_COINCIDENCIA)
    plano = _compacto(texto)
    exactas = [i for i, n in asignaturas if _compacto(n) == plano]
    if r := _unico(exactas, COINCIDE):
        return r
    parecidas = [i for i, n in asignaturas if _cercana(texto, n)]
    if r := _unico(parecidas, SUGERIDO):
        return r
    abreviadas = [
        i
        for i, n in asignaturas
        if numeral_final(n) == numeral_final(texto) and es_abreviatura(texto, n)
    ]
    return _unico(abreviadas, SUGERIDO) or Resultado(None, SIN_COINCIDENCIA)


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
