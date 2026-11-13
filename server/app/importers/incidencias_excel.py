"""Lectura de un Excel de incidencias (faltas y salidas anticipadas).

Solo LEE e interpreta; no decide horas ni registra asistencia. Las columnas se
reconocen por su encabezado (FECHA, DOCENTE/PROFESOR/NOMBRE, INCIDENCIA/TIPO,
HORA, OBSERVACIONES/MOTIVO), en cualquier orden. Lo que no se puede interpretar con
certeza queda vacío para que el usuario lo corrija: nunca se inventa un valor.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time

from app.importers.analisis import similitud
from app.services.comun import ErrorNegocio, normalizar

TAMANO_MAXIMO = 5 * 1024 * 1024
FILAS_MAXIMAS = 2000
FILAS_PARA_ENCABEZADO = 15

# Encabezados reconocidos (normalizados: mayúsculas y sin acentos), del más específico
# al más general.
COLUMNAS = {
    "fecha": ("FECHA DE LA INCIDENCIA", "FECHA DE INCIDENCIA", "FECHA", "DIA"),
    "docente": (
        "NOMBRE DEL DOCENTE",
        "NOMBRE DEL PROFESOR",
        "DOCENTE",
        "PROFESOR",
        "PROFESORA",
        "MAESTRO",
        "NOMBRE",
        "PERSONAL",
        "TRABAJADOR",
    ),
    "tipo": ("TIPO DE INCIDENCIA", "INCIDENCIA", "TIPO", "CONCEPTO", "MOVIMIENTO"),
    "hora": ("HORA DE SALIDA", "HORA", "SALIDA"),
    "detalle": ("OBSERVACIONES", "OBSERVACION", "MOTIVO", "COMENTARIOS", "DESCRIPCION", "NOTAS"),
}

MESES = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "SETIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

_HORA = re.compile(
    r"(?<![\d/:.-])(\d{1,2})(?:\s*:\s*(\d{2}))?\s*"
    r"(A\.?\s*M\b\.?|P\.?\s*M\b\.?|HRS?\b\.?|H\b)?(?![\d/:.-]*\d)",
)
_VACIAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "E"}


@dataclass
class FilaLeida:
    fila: int
    fecha_texto: str
    docente_texto: str
    tipo_texto: str
    hora_texto: str
    detalle_texto: str
    fecha: date | None
    tipo: str | None
    hora_salida: time | None


@dataclass
class Lectura:
    hoja: str
    columnas: dict[str, str]
    filas: list[FilaLeida] = field(default_factory=list)


# --- Interpretación de valores --------------------------------------------------------


def texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M") if valor.time() != time() else f"{valor:%Y-%m-%d}"
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return re.sub(r"\s+", " ", str(valor)).strip()


def leer_fecha(valor) -> date | None:
    """Fecha de una celda. Día/mes/año (como en México); si es ambigua o inválida, None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, int | float) and not isinstance(valor, bool):
        if 20000 < valor < 80000:  # número de serie de Excel
            from openpyxl.utils.datetime import from_excel

            return from_excel(valor).date()
        return None
    plano = normalizar(texto(valor))
    if not plano:
        return None
    try:
        if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", plano):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})", plano):
            anio = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(anio, int(m[2]), int(m[1]))
        palabras = re.sub(r"[,.]", " ", plano)
        m = re.search(r"(\d{1,2})\s+(?:DE\s+)?([A-Z]+)\s+(?:DE\s+|DEL\s+)?(\d{4})", palabras)
        if m and m[2] in MESES:
            return date(int(m[3]), MESES[m[2]], int(m[1]))
    except ValueError:
        return None
    return None


def leer_hora(valor) -> time | None:
    """'7:00 p. m.', '19:00', '7 pm', '19 hrs'. Sin minutos ni a.m./p.m./hrs no se acepta."""
    if isinstance(valor, datetime):
        return valor.time().replace(second=0, microsecond=0) if valor.time() != time() else None
    if isinstance(valor, time):
        return valor.replace(second=0, microsecond=0)
    plano = normalizar(texto(valor))
    for m in _HORA.finditer(plano):
        horas, minutos, marca = int(m[1]), int(m[2] or 0), (m[3] or "").replace(" ", "")
        if m[2] is None and not marca:
            continue
        if marca.startswith("P") and horas < 12:
            horas += 12
        elif marca.startswith("A") and horas == 12:
            horas = 0
        if 0 <= horas <= 23 and 0 <= minutos <= 59:
            return time(horas, minutos)
    return None


def leer_tipo(*textos: str) -> str | None:
    """'falta' o 'salida_anticipada'; si no es claro (o dice ambas), None."""
    plano = normalizar(" ".join(textos))
    salida = bool(re.search(r"\bSALIDA|\bSALIO\b|\bRETIRO\b|\bSE RETIRA", plano))
    falta = bool(re.search(r"\bFALTA|\bFALTO\b|\bINASISTENCIA|\bAUSENCIA|\bNO ASISTIO|^F$", plano))
    if salida and not falta:
        return "salida_anticipada"
    if falta and not salida:
        return "falta"
    return None


# --- Encabezados y filas -----------------------------------------------------------


def _columna(encabezado: str) -> str | None:
    plano = normalizar(encabezado)
    if not plano:
        return None
    for nombre, sinonimos in COLUMNAS.items():
        if any(plano == s for s in sinonimos):
            return nombre
    for nombre, sinonimos in COLUMNAS.items():
        if any(plano.startswith(s + " ") or plano.endswith(" " + s) for s in sinonimos):
            return nombre
    return None


def _encabezado(filas: list[tuple]) -> tuple[int, dict[str, int]] | None:
    for i, fila in enumerate(filas[:FILAS_PARA_ENCABEZADO]):
        columnas: dict[str, int] = {}
        for j, valor in enumerate(fila):
            nombre = _columna(texto(valor))
            if nombre and nombre not in columnas:
                columnas[nombre] = j
        if "fecha" in columnas and "docente" in columnas:
            return i, columnas
    return None


def leer(contenido: bytes) -> Lectura:
    """Lee la primera hoja que tenga columnas de fecha y docente."""
    if len(contenido) > TAMANO_MAXIMO:
        raise ErrorNegocio("El archivo es demasiado grande (máximo 5 MB)", 413)
    if not zipfile.is_zipfile(io.BytesIO(contenido)):
        raise ErrorNegocio("El archivo no es un Excel (.xlsx) válido", 422)
    from openpyxl import load_workbook

    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as error:  # openpyxl lanza errores variados ante archivos dañados
        raise ErrorNegocio("No se pudo leer el Excel: el archivo está dañado", 422) from error
    vistos: list[str] = []
    try:
        for hoja in libro.worksheets:
            filas = list(hoja.iter_rows(values_only=True, max_row=FILAS_MAXIMAS + 50))
            encontrado = _encabezado(filas)
            if encontrado is None:
                vistos += [texto(v) for f in filas[:3] for v in f if texto(v)]
                continue
            inicio, columnas = encontrado
            lectura = Lectura(
                hoja.title,
                {k: texto(filas[inicio][j]) for k, j in columnas.items()},
            )
            for numero, fila in enumerate(filas[inicio + 1 :], start=inicio + 2):

                def celda(nombre, fila=fila, columnas=columnas):
                    j = columnas.get(nombre)
                    return fila[j] if j is not None and j < len(fila) else None

                valores = {k: celda(k) for k in COLUMNAS}
                if not any(texto(v) for v in valores.values()):
                    continue
                if len(lectura.filas) >= FILAS_MAXIMAS:
                    raise ErrorNegocio(f"El archivo tiene más de {FILAS_MAXIMAS} filas", 422)
                tipo_t, detalle_t, hora_t = (
                    texto(valores["tipo"]),
                    texto(valores["detalle"]),
                    texto(valores["hora"]),
                )
                lectura.filas.append(
                    FilaLeida(
                        fila=numero,
                        fecha_texto=texto(valores["fecha"])[:60],
                        docente_texto=texto(valores["docente"])[:200],
                        tipo_texto=tipo_t[:200],
                        hora_texto=hora_t[:60],
                        detalle_texto=detalle_t,
                        fecha=leer_fecha(valores["fecha"]),
                        tipo=leer_tipo(tipo_t, detalle_t),
                        hora_salida=(
                            leer_hora(valores["hora"]) or leer_hora(tipo_t) or leer_hora(detalle_t)
                        ),
                    )
                )
            if not lectura.filas:
                raise ErrorNegocio("El Excel no tiene incidencias debajo del encabezado", 422)
            return lectura
    finally:
        libro.close()
    raise ErrorNegocio(
        "No se encontraron las columnas FECHA y DOCENTE (o PROFESOR / NOMBRE)",
        422,
        [f"Encabezados leídos: {', '.join(vistos[:12]) or 'ninguno'}"],
    )


# --- Docentes ---------------------------------------------------------------------


def _palabras(nombre: str) -> list[str]:
    return [p for p in re.sub(r"[^A-Z ]", " ", normalizar(nombre)).split() if p not in _VACIAS]


def buscar_docente(nombre: str, docentes: list[tuple[int, str]]) -> tuple[int | None, str]:
    """(id, estado). Ignora el orden: 'FRANCO LARA ERNESTO' = 'ERNESTO FRANCO LARA'.

    - coincide: mismas palabras que un único docente.
    - sugerido: un único docente contiene todas las palabras (≥2), o se parece mucho.
    - sin_coincidencia: ninguno o varios posibles. Nunca se asigna uno dudoso.
    """
    buscadas = _palabras(nombre)
    if not buscadas:
        return None, "sin_coincidencia"
    clave = sorted(buscadas)
    catalogo = [(i, _palabras(n)) for i, n in docentes]
    exactos = [i for i, p in catalogo if sorted(p) == clave]
    if len(exactos) == 1:
        return exactos[0], "coincide"
    if exactos:
        return None, "sin_coincidencia"
    if len(buscadas) >= 2:
        contenidos = [
            i
            for i, p in catalogo
            if set(buscadas) <= set(p) or (len(p) >= 2 and set(p) <= set(buscadas))
        ]
        if len(contenidos) == 1:
            return contenidos[0], "sugerido"
        if contenidos:
            return None, "sin_coincidencia"
    texto_buscado = " ".join(clave)
    parecidos = [i for i, p in catalogo if similitud(" ".join(sorted(p)), texto_buscado) >= 0.9]
    if len(parecidos) == 1:
        return parecidos[0], "sugerido"
    return None, "sin_coincidencia"
