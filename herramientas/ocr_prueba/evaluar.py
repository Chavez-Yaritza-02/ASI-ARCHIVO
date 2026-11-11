"""Compara la extracción OCR contra una transcripción verificada a mano.

Uso:
    uv run python herramientas/ocr_prueba/evaluar.py RESULTADO.json CARPETA_VERDAD [--anonimo]

CARPETA_VERDAD contiene:
- mapa.txt: una línea por página, "01p1 01" (página -> archivo de transcripción).
- NN.txt: transcripción en formato compacto, una línea por bloque:
      L 7-8 GESTIÓN ACADÉMICA||LMAC        (día, horas, actividad|grupo|aula)
  Días: L M X J V S. "7-8" son las filas de 07:00 y 08:00.

Se evalúan tres modos:
- sin catálogo: el texto tal como lo leyó el OCR.
- catálogo automático: se corrige con un catálogo armado solo con las lecturas del OCR
  (lo que podría hacer el importador la primera vez, sin datos previos).
- catálogo verificado: se corrige con las aulas y actividades reales (simula tener el
  catálogo ya capturado en la base de datos).

Con --anonimo los documentos se muestran como "Doc 01" en lugar del nombre,
para poder guardar el reporte sin datos personales.
"""

import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analisis import (  # noqa: E402
    CAMPOS,
    Catalogo,
    Celda,
    Conteo,
    comparar_celdas,
    leer_celda,
    normalizar,
)

_DIAS = {
    "L": "lunes",
    "M": "martes",
    "X": "miercoles",
    "J": "jueves",
    "V": "viernes",
    "S": "sabado",
}
MODOS = ("sin catálogo", "catálogo automático", "catálogo verificado")


def cargar_transcripcion(texto: str) -> dict[str, Celda]:
    celdas: dict[str, Celda] = {}
    for linea in texto.splitlines():
        if not linea.strip() or linea.startswith("#"):
            continue
        dia, horas, resto = linea.split(" ", 2)
        inicio, _, fin = horas.partition("-")
        actividad, grupo, aula = resto.split("|")
        for h in range(int(inicio), int(fin or inicio) + 1):
            clave = f"{_DIAS[dia]}-{h}"
            if clave in celdas:
                raise ValueError(f"Celda repetida en la transcripción: {clave}")
            celdas[clave] = Celda(actividad, grupo or None, aula or None)
    return celdas


def celdas_obtenidas(pagina: dict) -> dict[str, Celda]:
    """Vuelve a interpretar el texto OCR guardado (así se prueban cambios del analizador
    sin repetir el OCR, que es la parte lenta)."""
    resultado = {}
    for clave, datos in pagina["celdas"].items():
        celda = leer_celda(datos["texto"])
        if celda:
            resultado[clave] = celda
    return resultado


def corregir(celdas: dict[str, Celda], aulas: Catalogo, actividades: Catalogo) -> dict:
    return {
        k: replace(
            c, aula=aulas.corregir(c.aula)[0], actividad=actividades.corregir(c.actividad)[0]
        )
        for k, c in celdas.items()
    }


def evaluar(resultados: list[dict], carpeta: Path, anonimo: bool) -> str:
    mapa = dict(ln.split() for ln in (carpeta / "mapa.txt").read_text().splitlines() if ln)

    paginas = []  # (etiqueta, n, pagina, esperado, obtenido, nombre_real)
    for i, doc in enumerate(resultados, 1):
        etiqueta = f"Doc {i:02d}" if anonimo else doc["archivo"].removesuffix(".pdf")
        for n, pagina in enumerate(doc["paginas"], 1):
            esperado = cargar_transcripcion((carpeta / f"{mapa[f'{i:02d}p{n}']}.txt").read_text())
            nombre_real = normalizar(Path(doc["archivo"]).stem)
            paginas.append((etiqueta, n, pagina, esperado, celdas_obtenidas(pagina), nombre_real))

    leidas = [c for *_, o, _ in paginas for c in o.values()]
    reales = [c for *_, e, _, _ in paginas for c in e.values()]
    catalogos = {
        "catálogo automático": (
            Catalogo([c.aula for c in leidas], "aula"),
            Catalogo([c.actividad for c in leidas], "actividad"),
        ),
        "catálogo verificado": (
            Catalogo([c.aula for c in reales], "aula", verificado=True),
            Catalogo([c.actividad for c in reales], "actividad", verificado=True),
        ),
    }

    # Con el catálogo verificado: ¿cuántas celdas quedarían marcadas para revisión, y
    # cuántos errores pasarían sin marcar (silenciosos)? Esto es lo que más importa.
    aulas_v, actividades_v = catalogos["catálogo verificado"]
    marcadas = silenciosos = 0
    for *_, esperado, obtenido, _ in paginas:
        for clave, e in esperado.items():
            o = obtenido.get(clave)
            if o is None:
                marcadas += 1
                continue
            aula, ok_aula = aulas_v.corregir(o.aula) if o.aula else (None, e.aula is None)
            actividad, ok_act = actividades_v.corregir(o.actividad)
            if not (ok_aula and ok_act):
                marcadas += 1
            elif normalizar(aula) != normalizar(e.aula) or normalizar(actividad) != normalizar(
                e.actividad
            ):
                silenciosos += 1

    totales = {m: {c: Conteo() for c in CAMPOS} for m in MODOS}
    generales = {k: Conteo() for k in ("qr", "nombre_qr", "nombre_ocr", "nombre", "completo")}
    extra = 0
    filas = []
    por_doc: dict[str, dict] = {}
    for etiqueta, n, pagina, esperado, obtenido, nombre_real in paginas:
        por_modo = {"sin catálogo": comparar_celdas(esperado, obtenido)}
        for modo, (aulas, actividades) in catalogos.items():
            por_modo[modo] = comparar_celdas(esperado, corregir(obtenido, aulas, actividades))
        for modo, r in por_modo.items():
            for campo in CAMPOS:
                totales[modo][campo].correctos += r[campo].correctos
                totales[modo][campo].total += r[campo].total
        extra += por_modo["sin catálogo"]["celdas_extra"].total

        qr = pagina.get("qr") or {}
        ok_qr = normalizar(qr.get("docente")) == nombre_real
        ok_ocr = normalizar(pagina.get("docente_ocr")) == nombre_real
        horas_qr = qr.get("horas", {}).get("TOT")
        completo = horas_qr == len(obtenido)
        generales["qr"].sumar(bool(qr))
        generales["nombre_qr"].sumar(ok_qr)
        generales["nombre_ocr"].sumar(ok_ocr)
        generales["nombre"].sumar(ok_qr if qr else ok_ocr)
        generales["completo"].sumar(completo)

        r = por_modo["sin catálogo"]
        rv = por_modo["catálogo verificado"]
        d = por_doc.setdefault(
            etiqueta,
            {"paginas": 0, "versiones": set(), "sin_qr": 0, "celdas": 0, "revisar": []}
            | {c: Conteo() for c in ("posicion", "actividad", "grupo", "aula", "aula_cat")},
        )
        d["paginas"] += 1
        d["celdas"] += len(esperado)
        if qr:
            d["versiones"].add(qr["version"])
        else:
            d["sin_qr"] += 1
        for campo, origen in [
            ("posicion", r["posicion"]),
            ("actividad", r["actividad"]),
            ("grupo", r["grupo"]),
            ("aula", r["aula_equivalente"]),
            ("aula_cat", rv["aula"]),
        ]:
            d[campo].correctos += origen.correctos
            d[campo].total += origen.total
        errores_crudos = sum(r[c].total - r[c].correctos for c in ("actividad", "grupo", "aula"))
        errores_catalogo = sum(
            rv[c].total - rv[c].correctos for c in ("actividad", "grupo", "aula")
        )
        version = f"v{qr['version']}" if qr else "sin QR"
        filas.append(
            f"| {etiqueta} | {n} | {version} | {len(esperado)} | {len(obtenido)} "
            f"| {horas_qr if horas_qr is not None else '—'} | {r['posicion'].porcentaje:.0f}% "
            f"| {r['actividad'].porcentaje:.0f}% | {r['grupo'].porcentaje:.0f}% "
            f"| {r['aula'].porcentaje:.0f}% | {rv['aula'].porcentaje:.0f}% "
            f"| {'Sí' if ok_ocr else 'No'} | {errores_crudos} | {errores_catalogo} |"
        )

    def fila(titulo: str, campo: str) -> str:
        celdas = " | ".join(
            f"{totales[m][campo].porcentaje:.1f}% ({totales[m][campo].correctos}/"
            f"{totales[m][campo].total})"
            for m in MODOS
        )
        return f"| {titulo} | {celdas} |"

    salida = [
        "### Precisión por campo (celdas de una hora)",
        "",
        "| Campo | " + " | ".join(MODOS) + " |",
        "|---|---|---|---|",
        fila("Día y hora", "posicion"),
        fila("Asignatura/actividad (texto exacto)", "actividad_exacta"),
        fila("Asignatura/actividad (≈, mismo numeral)", "actividad"),
        fila("Grupo", "grupo"),
        fila("Aula (texto exacto)", "aula"),
        fila("Aula (O=0, I=1)", "aula_equivalente"),
        "",
        f"Celdas falsas (ruido leído como clase): {extra}",
        "",
        "Con catálogo verificado, el importador marcaría para revisión "
        f"{marcadas} de {len(reales)} celdas ({100 * marcadas / len(reales):.1f}%) y "
        f"quedarían **{silenciosos} errores sin marcar** (aceptados con confianza pero "
        "incorrectos).",
        "",
        "### Encabezado y control por página",
        "",
        "| Campo | Correctos | Total | Precisión |",
        "|---|---|---|---|",
    ]
    for clave, titulo in [
        ("qr", "Código QR leído"),
        ("nombre_qr", "Nombre del docente desde QR"),
        ("nombre_ocr", "Nombre del docente desde OCR del encabezado"),
        ("nombre", "Nombre del docente (QR y, si falta, OCR)"),
        ("completo", "Nº de celdas leídas = horas totales del QR"),
    ]:
        c = generales[clave]
        salida.append(f"| {titulo} | {c.correctos} | {c.total} | {c.porcentaje:.1f}% |")
    salida += [
        "",
        "### Resultados por documento",
        "",
        "Aula = sin catálogo, considerando O=0 e I=1. Aula (catálogo) = con catálogo verificado.",
        "",
        "| Documento | Páginas | Versiones (QR) | Celdas | Día/hora | Actividad | Grupo | Aula "
        "| Aula (catálogo) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for etiqueta, d in por_doc.items():
        versiones = ", ".join(f"v{v}" for v in sorted(d["versiones"]))
        if d["sin_qr"]:
            versiones += f"{', ' if versiones else ''}{d['sin_qr']} pág. sin QR"
        salida.append(
            f"| {etiqueta} | {d['paginas']} | {versiones} | {d['celdas']} "
            + "".join(
                f"| {d[c].porcentaje:.0f}% "
                for c in ("posicion", "actividad", "grupo", "aula", "aula_cat")
            )
            + "|"
        )
    salida += [
        "",
        "### Resultados por página",
        "",
        "Errores = celdas con actividad, grupo o aula incorrectos "
        "(crudo / con catálogo verificado).",
        "",
        "| Documento | Pág | Versión | Celdas reales | Celdas leídas | Horas QR | Día/hora "
        "| Actividad | Grupo | Aula | Aula (catálogo) | Nombre OCR | Errores "
        "| Errores (catálogo) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *filas,
    ]
    return "\n".join(salida) + "\n"


def main() -> None:
    resultados = json.loads(Path(sys.argv[1]).read_text())
    print(evaluar(resultados, Path(sys.argv[2]), anonimo="--anonimo" in sys.argv))


if __name__ == "__main__":
    main()
