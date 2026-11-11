"""Reportes de la bitácora en PDF (imprimible, con firmas) y Excel.

Ambos formatos se generan con librerías de Python puras (reportlab y openpyxl), que
funcionan igual en Windows y macOS sin instalar nada adicional.

Los reportes distinguen lo registrado (asistió, retardo, falta, justificado) de lo
"pendiente de verificar", que nunca se presenta como asistencia.
"""

import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.config import obtener_configuracion

NOMBRES_ESTADO = {
    "pendiente": "Pendiente de verificar",
    "inhabil": "Día inhábil",
    "asistio": "Asistió",
    "retardo": "Retardo",
    "falto": "Falta",
    "justificado": "Justificado",
}
COLORES_ESTADO = {
    "pendiente": "#fde68a",
    "inhabil": "#e5e7eb",
    "asistio": "#bbf7d0",
    "retardo": "#fed7aa",
    "falto": "#fecaca",
    "justificado": "#bfdbfe",
}
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
TIPOS_INCIDENCIA = {
    "comision": "Comisión",
    "permiso": "Permiso",
    "salida_anticipada": "Salida anticipada",
    "cambio_aula": "Cambio de aula",
    "otra": "Otra",
}
FIRMAS = [("Elaboró", "Asistente de Jefatura"), ("Vo. Bo.", "Jefatura de Electromecánica")]
ENCABEZADOS = [
    "Fecha",
    "Docente",
    "Turno",
    "Programado",
    "Actividades",
    "Entrada",
    "Salida",
    "Estado",
    "Observaciones",
]


def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def _hora(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def filas_reporte(dias: list[dict]) -> list[list[str]]:
    """Convierte bitácoras (servicio) en filas de texto comunes a PDF y Excel."""
    filas = []
    for d in dias:
        for f in d["filas"]:
            a = f["asistencia"] or {}
            notas = [
                a.get("observaciones") or "",
                a.get("justificacion") or "",
                f["motivo_inhabil"],
            ]
            if f["fuera_de_programacion"]:
                notas.append("Registro sin actividades programadas (el horario cambió)")
            actividades = "; ".join(
                f"{x['asignatura']}"
                + (f" {x['grupo']}" if x["grupo"] else "")
                + (f" ({x['aula']})" if x["aula"] else "")
                for x in f["actividades"]
            )
            filas.append(
                [
                    d["fecha"].strftime("%d/%m/%Y"),
                    f["docente"]["nombre"],
                    f["turno"].capitalize(),
                    f"{_hora(f['programado_inicio'])}–{_hora(f['programado_fin'])}",
                    actividades,
                    _hora(a.get("hora_entrada")),
                    _hora(a.get("hora_salida")),
                    NOMBRES_ESTADO[f["estado"]],
                    " · ".join(n for n in notas if n),
                ]
            )
    return filas


def resumen_total(dias: list[dict]) -> dict[str, int]:
    total = {e: 0 for e in NOMBRES_ESTADO}
    for d in dias:
        for estado, n in d["resumen"].items():
            total[estado] += n
    return total


def _generado() -> str:
    ahora = datetime.now(ZoneInfo(obtener_configuracion().zona_horaria))
    return ahora.strftime("Generado el %d/%m/%Y a las %H:%M")


# --- PDF ---------------------------------------------------------------------------


def pdf(titulo: str, subtitulo: str, dias: list[dict], incidencias: list) -> bytes:
    config = obtener_configuracion()
    salida = io.BytesIO()
    documento = SimpleDocTemplate(
        salida,
        pagesize=landscape(letter),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.4 * cm,
        title=titulo,
        author=config.dependencia,
    )
    estilos = getSampleStyleSheet()
    celda = ParagraphStyle("celda", parent=estilos["BodyText"], fontSize=7.5, leading=9)
    titulo_estilo = ParagraphStyle("t", parent=estilos["Title"], fontSize=14, spaceAfter=2)
    normal = ParagraphStyle("n", parent=estilos["BodyText"], fontSize=9)

    historia = [
        Paragraph(config.institucion, normal),
        Paragraph(config.dependencia, normal),
        Paragraph(titulo, titulo_estilo),
        Paragraph(subtitulo, normal),
        Spacer(1, 6),
    ]
    totales = resumen_total(dias)
    partes = [f"{NOMBRES_ESTADO[e]}: {n}" for e, n in totales.items() if n]
    historia.append(
        Paragraph(
            "Resumen: " + (" · ".join(partes) if partes else "sin docentes programados"), normal
        )
    )
    historia.append(Spacer(1, 6))

    filas = filas_reporte(dias)
    if filas:
        datos = [ENCABEZADOS] + [[Paragraph(str(c), celda) for c in f] for f in filas]
        anchos = [1.8, 4.6, 1.8, 2.0, 6.2, 1.3, 1.3, 2.4, 4.2]
        tabla = Table(datos, colWidths=[a * cm for a in anchos], repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a37")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9ca3af")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        for i, f in enumerate(filas, 1):
            clave = next(k for k, v in NOMBRES_ESTADO.items() if v == f[7])
            estilo.append(("BACKGROUND", (7, i), (7, i), colors.HexColor(COLORES_ESTADO[clave])))
        tabla.setStyle(TableStyle(estilo))
        historia.append(tabla)
    else:
        historia.append(Paragraph("No hay docentes programados ni registros.", normal))

    if incidencias:
        historia += [Spacer(1, 8), Paragraph("<b>Incidencias</b>", normal)]
        for i in incidencias:
            quien = f" — {i.docente.nombre}" if i.docente else ""
            historia.append(
                Paragraph(
                    f"{i.fecha:%d/%m/%Y} · {TIPOS_INCIDENCIA[i.tipo]}{quien}: {i.descripcion}",
                    celda,
                )
            )

    firmas = Table(
        [
            ["", "", ""],
            ["_" * 38, "", "_" * 38],
            [FIRMAS[0][0], "", FIRMAS[1][0]],
            [FIRMAS[0][1], "", FIRMAS[1][1]],
        ],
        colWidths=[8 * cm, 6 * cm, 8 * cm],
        rowHeights=[1.4 * cm, None, None, None],
    )
    firmas.setStyle(
        TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 8.5)])
    )
    historia += [Spacer(1, 12), KeepTogether(firmas)]

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(1.2 * cm, 0.8 * cm, _generado())
        canvas.drawRightString(landscape(letter)[0] - 1.2 * cm, 0.8 * cm, f"Página {doc.page}")
        canvas.restoreState()

    documento.build(historia, onFirstPage=pie, onLaterPages=pie)
    return salida.getvalue()


# --- Excel -------------------------------------------------------------------------------


def xlsx(titulo: str, subtitulo: str, dias: list[dict], incidencias: list) -> bytes:
    config = obtener_configuracion()
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Bitácora"
    negrita = Font(bold=True)
    for texto in (config.institucion, config.dependencia):
        hoja.append([texto])
    hoja.append([titulo])
    hoja["A3"].font = Font(bold=True, size=14)
    hoja.append([subtitulo])
    hoja.append([_generado()])
    hoja.append([])
    inicio = hoja.max_row + 1
    hoja.append(ENCABEZADOS)
    borde = Border(*(Side(style="thin", color="9CA3AF"),) * 4)
    for c in hoja[inicio]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F2A37")
    for f in filas_reporte(dias):
        hoja.append(f)
        fila = hoja[hoja.max_row]
        clave = next(k for k, v in NOMBRES_ESTADO.items() if v == f[7])
        fila[7].fill = PatternFill("solid", fgColor=COLORES_ESTADO[clave].lstrip("#"))
        for c in fila:
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = borde
    for i, ancho in enumerate([11, 32, 12, 13, 48, 9, 9, 22, 40], 1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.freeze_panes = hoja.cell(row=inicio + 1, column=1)
    hoja.auto_filter.ref = f"A{inicio}:I{hoja.max_row}"

    resumen = libro.create_sheet("Resumen")
    resumen.append(["Estado", "Total"])
    for c in resumen[1]:
        c.font = negrita
    for estado, n in resumen_total(dias).items():
        resumen.append([NOMBRES_ESTADO[estado], n])
    if incidencias:
        resumen.append([])
        resumen.append(["Incidencias"])
        resumen.cell(row=resumen.max_row, column=1).font = negrita
        for i in incidencias:
            resumen.append(
                [
                    i.fecha.strftime("%d/%m/%Y"),
                    TIPOS_INCIDENCIA[i.tipo],
                    i.docente.nombre if i.docente else "",
                    i.descripcion,
                ]
            )
    resumen.column_dimensions["A"].width = 24
    resumen.column_dimensions["D"].width = 60

    hoja.append([])
    hoja.append([])
    hoja.append(["_" * 30, "", "", "", "_" * 30])
    hoja.append([FIRMAS[0][0], "", "", "", FIRMAS[1][0]])
    hoja.append([FIRMAS[0][1], "", "", "", FIRMAS[1][1]])
    hoja.print_options.gridLines = False
    hoja.page_setup.orientation = "landscape"
    hoja.page_setup.fitToWidth = 1
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
