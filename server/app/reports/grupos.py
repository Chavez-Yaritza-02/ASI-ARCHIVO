"""Horario semanal por grupo, PDF y Excel sin nombres de firmantes."""

import io
from html import escape

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import obtener_configuracion
from app.reports.bitacora import FIRMAS


def matriz(datos):
    filas = [["Fecha", "Materia", "Docente", "Aula", "Entrada", "Salida", "Avisos"]]
    for b in datos["bloques"]:
        avisos = [b["aviso_calendario"]] if not b["habil"] else []
        if b["conflictos"]:
            avisos.append("Traslape de grupo")
        filas.append(
            [
                str(b["fecha"]),
                b["materia"],
                b["docente"],
                b["aula"] or "Sin aula",
                b["inicio"].strftime("%H:%M"),
                b["fin"].strftime("%H:%M"),
                "; ".join(avisos),
            ]
        )
    return filas


def exportar(datos, formato):
    cfg = obtener_configuracion()
    titulo = f"Horario semanal · {datos['grupo']}"
    subtitulo = f"{datos['desde']} a {datos['hasta']} · Periodo #{datos['periodo_id']}"
    avisos = datos["aviso"]
    if datos["horarios_sin_vigencia_confirmada"]:
        avisos += " Hay versiones excluidas por vigencia desconocida."
    filas = matriz(datos)
    salida = io.BytesIO()
    if formato == "xlsx":
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Horario de grupo"
        for fila in [[cfg.institucion], [cfg.dependencia], [titulo], [subtitulo], [avisos], *filas]:
            limpia = [ILLEGAL_CHARACTERS_RE.sub("", str(v)) for v in fila]
            hoja.append(limpia)
            for celda in hoja[hoja.max_row]:
                # Nunca interpretar fórmulas procedentes de catálogos.
                celda.data_type = "s"
        hoja.freeze_panes = "A7"
        hoja.auto_filter.ref = f"A6:G{hoja.max_row}"
        for columna, ancho in zip("ABCDEFG", [14, 28, 34, 18, 12, 12, 40], strict=True):
            hoja.column_dimensions[columna].width = ancho
        for cargo, puesto in FIRMAS:
            hoja.append([cargo, puesto])
        libro.save(salida)
    else:
        estilos = getSampleStyleSheet()
        p = lambda t: Paragraph(escape(str(t)), estilos["Normal"])  # noqa: E731
        historia = [
            p(cfg.institucion),
            p(cfg.dependencia),
            p(titulo),
            p(subtitulo),
            p(avisos),
            Spacer(1, 12),
        ]
        tabla = Table(
            [[p(v) for v in fila] for fila in filas],
            colWidths=[65, 125, 140, 55, 45, 45, 165],
            repeatRows=1,
        )
        tabla.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        historia += [
            tabla,
            Spacer(1, 16),
            *[p(f"{a}: __________________ · {b}") for a, b in FIRMAS],
        ]
        SimpleDocTemplate(
            salida,
            pagesize=landscape(letter),
            leftMargin=24,
            rightMargin=24,
            topMargin=24,
            bottomMargin=24,
        ).build(historia)
    return salida.getvalue()
