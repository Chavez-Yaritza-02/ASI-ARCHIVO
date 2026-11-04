"""Funciones puras de la prueba de OCR (sin dependencias de imagen ni Tesseract).

Aquí está la lógica que probablemente reutilizará el importador de la Etapa 3:
interpretar el código QR, interpretar el texto de una celda, unir horas
consecutivas en bloques y comparar contra una transcripción verificada.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"]

# --- Encabezado desde el QR ---------------------------------------------------


@dataclass
class Encabezado:
    unidad: str
    periodo: str
    docente: str
    nomina: str
    fecha: str
    vigencia_inicio: str
    vigencia_fin: str
    version: int
    horas: dict[str, int] = field(default_factory=dict)


_HORAS_QR = re.compile(r"([A-Z]+)\[(\d+)\]")  # "0GTUT[0]" -> ("GTUT", "0")


def leer_qr(texto: str) -> Encabezado | None:
    """Interpreta el texto del QR del horario institucional.

    Formato observado (separado por comas):
    UNIDAD,PERIODO,DOCENTE,NOMINA,FECHA,VIGENCIA,VERSION,CLAVE[horas],CLAVE[horas],...
    Ejemplo de contadores: MAT[25] = horas de asignaturas, TOT[40] = horas totales.
    """
    partes = [p.strip() for p in texto.split(",")]
    if len(partes) < 7 or not partes[6].isdigit():
        return None
    vigencia = re.match(r"(\d{4}-\d{2}-\d{2})\s+AL\s+(\d{4}-\d{2}-\d{2})", partes[5])
    if not vigencia:
        return None
    horas: dict[str, int] = {}
    for clave, valor in _HORAS_QR.findall(",".join(partes[7:])):
        horas[clave] = horas.get(clave, 0) + int(valor)
    return Encabezado(
        unidad=partes[0],
        periodo=partes[1],
        docente=partes[2],
        nomina=partes[3],
        fecha=partes[4],
        vigencia_inicio=vigencia.group(1),
        vigencia_fin=vigencia.group(2),
        version=int(partes[6]),
        horas=horas,
    )


# --- Celdas de la cuadrícula --------------------------------------------------


@dataclass(frozen=True)
class Celda:
    actividad: str
    grupo: str | None = None
    aula: str | None = None


_GRUPO = re.compile(r"Grupo\s*[:;.,]?\s*([A-Za-z0-9]{1,4})\b", re.IGNORECASE)
# El aula es el resto de la línea: admite "Sala EM", "L4.0", "O-LabQuimi", "DOM-03".
_AULA = re.compile(r"Aula\s*[:;.,]?\s*(\S.*)$", re.IGNORECASE)
# El OCR en español suele leer "A" como "Á". Esta tabla quita acentos sin cambiar
# la longitud del texto, para que las posiciones encontradas sigan siendo válidas.
_RUIDO_EXTREMOS = re.compile(r"^[~|_—–\-\s]+|^[a-z]\s|\s[a-z]$")
_SIN_ACENTOS = str.maketrans("ÁÉÍÓÚÀÈÌÒÙáéíóúàèìòù", "AEIOUAEIOUaeiouaeiou")


def corregir_clave(clave: str) -> str:
    """Corrige la confusión O/0 en claves como 'CUBO1' -> 'CUB01' o 'MO4' -> 'M04'."""
    clave = re.sub(r"\s+", " ", clave.upper())
    return "".join(
        "0" if c == "O" and any(v.isdigit() for v in clave[max(i - 1, 0) : i + 2]) else c
        for i, c in enumerate(clave)
    )


def leer_celda(texto: str) -> Celda | None:
    """Convierte el texto OCR de una celda en actividad, grupo y aula.

    Formato de celda: una o más líneas con la actividad, y al final
    "Grupo: X Aula: Y" (clases) o solo "Aula: Y" (otras actividades).
    """
    # Las líneas de la cuadrícula aparecen como "~", "|", "—" o una letra minúscula
    # suelta al inicio o al final ("DINAMICA i", "i Grupo: A"). Se quitan.
    lineas = [_RUIDO_EXTREMOS.sub("", ln).strip(" |_—–-~") for ln in texto.splitlines()]
    lineas = [ln for ln in lineas if len(ln) > 1]
    if not lineas:
        return None
    grupo = aula = None
    actividad: list[str] = []
    for ln in lineas:
        plano = ln.translate(_SIN_ACENTOS)
        g, a = _GRUPO.search(plano), _AULA.search(plano)
        if g or a:
            grupo = grupo or (g.group(1).upper() if g else None)
            aula = aula or (corregir_clave(a.group(1).strip(" .,;:'|")) if a else None)
            antes = ln[: min(m.start() for m in (g, a) if m)].strip()
            if antes:
                actividad.append(antes)
        else:
            actividad.append(ln)
    nombre = " ".join(actividad).strip()
    # Toda celda real termina en "Grupo: X Aula: Y" o "Aula: Y". Sin esa marca se
    # trata de ruido (firmas, sellos o anotaciones a mano) y se descarta.
    if grupo is None and aula is None:
        return None
    return Celda(actividad=nombre, grupo=grupo, aula=aula)


# --- Bloques ------------------------------------------------------------------


@dataclass(frozen=True)
class Bloque:
    dia: str
    inicio: int  # hora entera, p. ej. 7 = 07:00
    fin: int
    actividad: str
    grupo: str | None
    aula: str | None


def agrupar_bloques(celdas: dict[str, Celda]) -> list[Bloque]:
    """Une horas consecutivas del mismo día con idéntica actividad, grupo y aula.

    Las claves de `celdas` tienen la forma "dia-hora", p. ej. "lunes-7".
    """
    por_dia: dict[str, dict[int, Celda]] = {}
    for clave, celda in celdas.items():
        dia, hora = clave.rsplit("-", 1)
        por_dia.setdefault(dia, {})[int(hora)] = celda
    bloques: list[Bloque] = []
    for dia in DIAS:
        horas = por_dia.get(dia, {})
        for h in sorted(horas):
            c = horas[h]
            ultimo = bloques[-1] if bloques else None
            if (
                ultimo
                and ultimo.dia == dia
                and ultimo.fin == h
                and (ultimo.actividad, ultimo.grupo, ultimo.aula) == (c.actividad, c.grupo, c.aula)
            ):
                bloques[-1] = Bloque(dia, ultimo.inicio, h + 1, c.actividad, c.grupo, c.aula)
            else:
                bloques.append(Bloque(dia, h, h + 1, c.actividad, c.grupo, c.aula))
    return bloques


# --- Comparación contra la transcripción verificada ---------------------------


def normalizar(texto: str | None) -> str:
    """Mayúsculas, sin acentos y sin signos: 'Diseño Herram.' -> 'DISENO HERRAM'."""
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", sin_acentos.upper()).strip()


def similitud(a: str, b: str) -> float:
    """Similitud 0..1 basada en distancia de edición (Levenshtein)."""
    a, b = normalizar(a), normalizar(b)
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + (ca != cb)))
        previa = actual
    return 1 - previa[-1] / max(len(a), len(b))


UMBRAL_ACTIVIDAD = 0.85  # tolera 1–2 letras distintas en nombres largos


def clave_equivalente(clave: str | None) -> str:
    """Forma comparable de una clave de aula o grupo.

    En la tipografía de estos horarios la O y el 0, y la I y el 1, son
    prácticamente idénticos; el OCR no puede distinguirlos. Se tratan como
    iguales y la ambigüedad se resuelve después con el catálogo de aulas.
    """
    return normalizar(clave).replace(" ", "").replace("O", "0").replace("I", "1")


def _numeral_final(texto: str) -> str:
    """Numeral romano al final del nombre ('TALL. INV. II' -> 'II'), tolerando 1/l/!."""
    m = re.search(r"[\s.]([IVXl1!|]+)\.?\s*$", texto)
    return m.group(1).upper().translate(str.maketrans("L1!|", "IIII")) if m else ""


def actividad_exacta(esperada: str, obtenida: str) -> bool:
    return normalizar(esperada) == normalizar(obtenida)


def actividad_aproximada(esperada: str, obtenida: str) -> bool:
    """Casi igual y con el mismo numeral final ('Avan I' no es lo mismo que 'Avan II')."""
    return similitud(esperada, obtenida) >= UMBRAL_ACTIVIDAD and _numeral_final(
        esperada
    ) == _numeral_final(obtenida)


@dataclass
class Conteo:
    correctos: int = 0
    total: int = 0

    def sumar(self, ok: bool) -> None:
        self.total += 1
        self.correctos += int(ok)

    @property
    def porcentaje(self) -> float:
        return 100.0 * self.correctos / self.total if self.total else 100.0


CAMPOS = ("posicion", "actividad_exacta", "actividad", "grupo", "aula", "aula_equivalente")


def comparar_celdas(esperado: dict[str, Celda], obtenido: dict[str, Celda]) -> dict[str, Conteo]:
    """Compara celda por celda (clave "dia-hora"). Devuelve conteos por campo.

    - posicion: la celda ocupada se detectó en el día y la hora correctos.
    - actividad_exacta: mismo texto (sin acentos ni signos).
    - actividad: casi igual (tolera 1–2 letras) y con el mismo numeral final.
    - grupo, aula: iguales tras normalizar.
    - aula_equivalente: igual considerando O=0 e I=1.
    - celdas_extra: celdas detectadas donde no hay nada (deben ser 0).
    Si una celda no se detectó, cuenta como error en todos los campos.
    """
    r = {k: Conteo() for k in CAMPOS}
    for clave, e in esperado.items():
        o = obtenido.get(clave)
        r["posicion"].sumar(o is not None)
        if o is None:
            for campo in CAMPOS[1:]:
                r[campo].sumar(False)
            continue
        r["actividad_exacta"].sumar(actividad_exacta(e.actividad, o.actividad))
        r["actividad"].sumar(actividad_aproximada(e.actividad, o.actividad))
        r["grupo"].sumar(clave_equivalente(e.grupo) == clave_equivalente(o.grupo))
        r["aula"].sumar(normalizar(e.aula) == normalizar(o.aula))
        r["aula_equivalente"].sumar(clave_equivalente(e.aula) == clave_equivalente(o.aula))
    extra = Conteo()
    extra.total = extra.correctos = len(set(obtenido) - set(esperado))
    r["celdas_extra"] = extra
    return r


def celda_a_dict(c: Celda) -> dict:
    return asdict(c)


# --- Corrección con catálogo --------------------------------------------------

# Pares que el OCR confunde en estas claves: letra -> dígito parecido.
_CONFUSIONES = str.maketrans("OQDISGBZ", "00015682")
_FORMA_AULA = re.compile(r"^[A-Z]{1,5}-?\d{1,2}$")  # M05, CUB01, DOM-10, INV07


def esqueleto(clave: str | None) -> str:
    """Forma de una clave inmune a las confusiones típicas: 'MOS', 'M05' -> 'M05'."""
    return normalizar(clave).replace(" ", "").translate(_CONFUSIONES)


def _igual_o_un_caracter_extra(a: str, b: str) -> bool:
    """'M003' ~ 'M03' (el OCR duplicó un carácter). No acepta sustituciones: 'M01' != 'M02'."""
    if a == b:
        return True
    corta, larga = sorted((a, b), key=len)
    if len(larga) - len(corta) != 1:
        return False
    return any(larga[:i] + larga[i + 1 :] == corta for i in range(len(larga)))


UMBRAL_CATALOGO = 0.9  # más estricto: "MEC. DE MATER" y "MEC. DE MATERIA" son materias distintas


class Catalogo:
    """Valores válidos de un campo (aulas o actividades) para corregir lecturas del OCR.

    - verificado=True: los valores ya son correctos (en la Etapa 3 vendrán de la base de
      datos). Cada valor distinto es una entrada; nunca se fusionan.
    - verificado=False: catálogo armado con las propias lecturas del OCR. Las variantes
      parecidas se agrupan y se elige la más plausible como representante.
    """

    def __init__(self, valores: list[str | None], tipo: str, verificado: bool = False):
        assert tipo in ("aula", "actividad")
        self.tipo = tipo
        frecuencia: dict[str, int] = {}
        for v in valores:
            if v:
                frecuencia[v] = frecuencia.get(v, 0) + 1
        self.grupos: list[list[str]] = []
        for v in sorted(frecuencia, key=lambda x: -frecuencia[x]):
            grupo = None
            if not verificado:
                grupo = next((g for g in self.grupos if self._parecidos(g[0], v)), None)
            if grupo is None:
                self.grupos.append([v])
            else:
                grupo.append(v)
        self.representantes = [self._elegir(g, frecuencia) for g in self.grupos]

    def _parecidos(self, a: str, b: str) -> bool:
        if self.tipo == "aula":
            return _igual_o_un_caracter_extra(esqueleto(a), esqueleto(b))
        return similitud(a, b) >= UMBRAL_CATALOGO and _numeral_final(a) == _numeral_final(b)

    def _elegir(self, grupo: list[str], frecuencia: dict[str, int]) -> str:
        if self.tipo == "aula":

            def plausibilidad(v: str) -> tuple[bool, int]:
                forma = bool(_FORMA_AULA.match(normalizar(v).replace(" ", "-")))
                return forma, frecuencia[v]

            return max(grupo, key=plausibilidad)
        return max(grupo, key=lambda v: frecuencia[v])

    def _niveles(self):
        """Reglas de coincidencia, de la más estricta a la más flexible."""
        yield lambda a, b: normalizar(a) == normalizar(b)
        if self.tipo == "aula":
            yield lambda a, b: esqueleto(a) == esqueleto(b)
            yield lambda a, b: _igual_o_un_caracter_extra(esqueleto(a), esqueleto(b))
        else:
            yield self._parecidos

    def corregir(self, valor: str | None) -> tuple[str | None, bool]:
        """Devuelve (valor corregido, encontrado).

        Se usa el primer nivel con alguna coincidencia; si ahí hay más de una entrada
        posible, el valor no se cambia y debe revisarse a mano.
        """
        if not valor:
            return valor, False
        for coincide in self._niveles():
            candidatos = {
                r
                for g, r in zip(self.grupos, self.representantes, strict=True)
                if any(coincide(v, valor) for v in g)
            }
            if len(candidatos) == 1:
                return candidatos.pop(), True
            if candidatos:
                return valor, False
        return valor, False
