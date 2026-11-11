"""Reportes horarios en minutos exactos y horas decimales; sin créditos por turno."""

import io
from html import escape

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import obtener_configuracion
from app.reports.bitacora import FIRMAS, _generado
from app.services.asistencia_hora import METRICAS, totales

ESTADOS = {
    "asistio": "Asistió",
    "falto": "Falta",
    "retardo": "Retardo",
    "justificado": "Justificado",
    "parcial": "Parcial",
    "pendiente": "Pendiente de verificar",
    "inhabil": "Suspendida / inhábil",
}
ENCABEZADOS = [
    "Fecha",
    "Docente",
    "Actividad / grupo / aula",
    "Programado",
    "Estado",
    "Cumplidos min",
    "Faltantes min",
    "Justificados min",
    "Observaciones",
]
AVISO = (
    "Los pendientes no son faltas. Las suspensiones no se exigen sin excepción autorizada. "
    "Los registros por turno no acreditan horas. Los históricos fuera del programa actual "
    "se conservan separados de los totales. Horas decimales = minutos / 60."
)


def _fila(f):
    a = f["asistencia"] or {}
    notas = [a.get("observaciones"), a.get("justificacion"), f.get("motivo_inhabil")]
    if f.get("bloqueada_por_registro_previo"):
        notas.append("Revisar registro anterior que se traslapa: no duplicar captura")
    return [
        str(f["fecha"]),
        f["docente_nombre"],
        " · ".join(str(f[k]) for k in ("asignatura", "tipo_actividad", "grupo", "aula") if f[k]),
        f"{f['programado_inicio']:%H:%M}–{f['programado_fin']:%H:%M}",
        ESTADOS[f["estado"]],
        f["minutos"]["cumplidas"],
        f["minutos"]["faltantes"],
        f["minutos"]["justificadas"],
        " · ".join(n for n in notas if n),
    ]


def exportar(datos, formato):
    cfg = obtener_configuracion()
    titulo = "Asistencia por hora programada"
    subtitulo = f"{datos['desde']} a {datos['hasta']}"
    filas = [f for d in datos["dias"] for f in d["filas"]]
    fuera = [f for d in datos["dias"] for f in d["registros_fuera_de_programacion"]]
    por_docente = {}
    for f in filas:
        por_docente.setdefault((f["docente_id"], f["docente_nombre"]), []).append(f)
    resumen = [["Concepto", "Minutos exactos", "Horas decimales"]]
    resumen += [
        [k.capitalize(), datos["totales"]["minutos"][k], datos["totales"]["horas"][k]]
        for k in METRICAS
    ]
    legados = sum(len(d["registros_por_turno_sin_convertir"]) for d in datos["dias"])
    desconocidos = {
        id_ for d in datos["dias"] for id_ in d.get("horarios_sin_vigencia_confirmada", [])
    }
    aviso = AVISO
    if desconocidos:
        aviso += (
            f" Hay {len(desconocidos)} versiones con vigencia desconocida excluidas; "
            "los totales no representan horas de esas versiones."
        )
    salida = io.BytesIO()
    if formato == "xlsx":
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Asistencia por hora"
        for texto in (cfg.institucion, cfg.dependencia, titulo, subtitulo, _generado(), aviso):
            hoja.append([texto])
        hoja.append(ENCABEZADOS)
        for f in filas:
            hoja.append(_fila(f))
        hoja.freeze_panes = "A8"
        hoja.auto_filter.ref = f"A7:I{hoja.max_row}"
        for fila in hoja:
            for celda in fila:
                celda.alignment = Alignment(wrap_text=True, vertical="top")
        for i, ancho in enumerate([13, 32, 40, 15, 24, 16, 16, 18, 50], 1):
            hoja.column_dimensions[get_column_letter(i)].width = ancho
        hoja.page_setup.orientation = "landscape"
        hoja.page_setup.fitToWidth = 1
        tot = libro.create_sheet("Resumen de horas")
        for fila in resumen:
            tot.append(fila)
        tot.append(["Registros por turno sin convertir", legados])
        docentes = libro.create_sheet("Por docente")
        docentes.append(
            [
                "Docente",
                *[k.capitalize() + " min" for k in METRICAS],
                *[k.capitalize() + " h" for k in METRICAS],
            ]
        )
        for (_id, nombre), ff in sorted(por_docente.items()):
            t = totales(ff)
            docentes.append([nombre, *t["minutos"].values(), *t["horas"].values()])
        anteriores = libro.create_sheet("Fuera de programación")
        anteriores.append(["Historial conservado; excluido de los totales actuales"])
        anteriores.append(ENCABEZADOS)
        for f in fuera:
            anteriores.append(_fila(f))
        for cargo, puesto in FIRMAS:
            hoja.append([cargo, puesto])
        for pagina in libro:
            for celda in pagina[1]:
                celda.font = Font(bold=True)
            for fila in pagina:
                for celda in fila:
                    if isinstance(celda.value, str):
                        celda.value = ILLEGAL_CHARACTERS_RE.sub("", celda.value)
                        celda.data_type = "s"
        libro.save(salida)
    else:
        estilos = getSampleStyleSheet()
        estilos["Normal"].fontSize = 7
        estilos["Normal"].leading = 9

        def parrafo(texto):
            return Paragraph(escape(str(texto)), estilos["Normal"])

        historia = [
            parrafo(x)
            for x in (cfg.institucion, cfg.dependencia, titulo, subtitulo, _generado(), aviso)
        ]
        historia.append(Spacer(1, 8))
        resumen_pdf = Table([[parrafo(v) for v in f] for f in resumen], colWidths=[130, 100, 100])
        historia.extend([resumen_pdf, parrafo(f"Registros por turno sin convertir: {legados}")])
        for nombre, ff in [
            ("Detalle horario", filas),
            ("Historial fuera de programación (excluido de los totales)", fuera),
        ]:
            historia.extend([Spacer(1, 10), parrafo(nombre)])
            tabla = Table(
                [[parrafo(v) for v in f] for f in [ENCABEZADOS, *map(_fila, ff)]],
                colWidths=[50, 90, 120, 55, 75, 40, 40, 45, 129],
                repeatRows=1,
            )
            tabla.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            historia.append(tabla)
        historia.extend(
            [Spacer(1, 12), *[parrafo(f"{a}: __________________ · {b}") for a, b in FIRMAS]]
        )
        SimpleDocTemplate(
            salida,
            pagesize=landscape(letter),
            leftMargin=24,
            rightMargin=24,
            topMargin=24,
            bottomMargin=24,
        ).build(historia)
    return salida.getvalue()
