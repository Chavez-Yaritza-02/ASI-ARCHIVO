"""Recorrido funcional completo y evidencias visuales con información ficticia."""

import os
from pathlib import Path

import pymupdf
import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from asi_cliente.api.cliente import ErrorApi
from asi_cliente.views import asistencia_hora as vistas
from asi_cliente.views.asistencia_hora import DialogoAsistenciaHora
from asi_cliente.views.asistencia_lote import DialogoCapturaLote
from asi_cliente.views.ventana_principal import VentanaPrincipal

pytest_plugins = ["server.tests.test_interfaz_asistencia_hora"]


def test_lote_rechaza_todo_si_una_hora_es_invalida(api_horas):
    filas = api_horas.get("/bitacora/horas", fecha="2026-11-02")["filas"]
    registros = [
        {
            "docente_id": f["docente_id"],
            "fecha": f["fecha"],
            "bloque_id": f["bloque_id"],
            "programado_inicio": f["programado_inicio"],
            "estado": "asistio",
        }
        for f in filas[:2]
    ]
    registros[1]["estado"] = "justificado"
    with pytest.raises(ErrorApi) as error:
        api_horas.post("/asistencias/horas/lote", {"registros": registros})
    assert "justificación" in str(error.value)
    assert all(
        f["asistencia"] is None
        for f in api_horas.get("/bitacora/horas", fecha="2026-11-02")["filas"]
    )


def test_recorrido_completo_y_revision_visual(
    qtbot, api_horas, escuela_horas, monkeypatch, tmp_path
):
    e = escuela_horas
    h = api_horas.post(
        "/horarios",
        {"docente_id": e["docente"], "periodo_id": e["periodo"], "basado_en_id": e["horario"]},
    )
    api_horas.put(
        f"/horarios/{h['id']}/bloques",
        [
            {
                "dia": "lunes",
                "hora_inicio": "07:00",
                "hora_fin": "14:00",
                "asignatura_id": e["calculo"],
                "grupo_id": e["grupo_a"],
                "aula_id": e["m01"],
            }
        ],
    )
    api_horas.post(f"/horarios/{h['id']}/confirmar", {"vigente_desde": "2026-11-01"})
    errores = []
    monkeypatch.setattr(vistas, "mostrar_error", lambda _p, error: errores.append(str(error)))
    ventana = VentanaPrincipal(api_horas.usuario, api_horas)
    qtbot.addWidget(ventana)
    ventana.resize(1480, 900)
    v = ventana.abrir_seccion("Asistencia por hora")
    v.fecha.setDate(QDate(2026, 11, 2))
    ventana.show()
    qtbot.waitUntil(ventana.isVisible)
    assert len(v.tabla.filas) == 7
    ruta = Path(os.environ.get("ASI_REVISION_VISUAL_DIR", tmp_path))
    ruta.mkdir(parents=True, exist_ok=True)
    lote_real = DialogoCapturaLote

    def formulario_lote(filas, padre):
        d = lote_real(filas, padre)
        for i, estado in enumerate(("asistio", "falto", "retardo")):
            controles = d.controles[i]
            controles[0].setCurrentIndex(controles[0].findData(estado))
            if estado == "retardo":
                controles[1].setTime(controles[1].time().addSecs(15 * 60))
        d.show()
        qtbot.wait(30)
        d.grab().save(str(ruta / "02-captura-lote.png"))
        QTimer.singleShot(100, d.accept)
        return d

    monkeypatch.setattr(vistas, "DialogoCapturaLote", formulario_lote)
    v.tabla.clearSelection()
    for fila in range(3):
        v.tabla.selectionModel().select(
            v.tabla.model().index(fila, 0),
            v.tabla.selectionModel().SelectionFlag.Select
            | v.tabla.selectionModel().SelectionFlag.Rows,
        )
    v.boton_lote.click()
    assert [f["estado"] for f in v.tabla.filas[:3]] == ["asistio", "falto", "retardo"]

    def capturar(fila, estado, corregir=False):
        def formulario(f, padre):
            d = DialogoAsistenciaHora(f, padre)
            d.estado.setCurrentIndex(d.estado.findData(estado))
            if estado == "justificado":
                d.justificacion.setText("Permiso ficticio documentado")
            if estado == "parcial":
                d.salida.setTime(d.entrada.time().addSecs(30 * 60))
                d.minutos_justificados.setValue(15)
                d.justificacion.setText("Justificación ficticia de 15 minutos")
            if corregir:
                d.motivo.setText("Verificación ficticia: sí cumplió esta hora")
            QTimer.singleShot(100, d.accept)
            return d

        monkeypatch.setattr(vistas, "DialogoAsistenciaHora", formulario)
        v.tabla.clearSelection()
        v.tabla.selectRow(fila)
        v.boton_registrar.click()

    capturar(4, "parcial")
    capturar(3, "justificado")
    ventana.grab().save(str(ruta / "01-asistencia-estados.png"))
    capturar(1, "asistio", True)
    a = v.tabla.filas[1]["asistencia"]
    historial = api_horas.get(f"/asistencias/horas/{a['id']}/historial")
    assert [c["accion"] for c in historial] == ["registrar", "corregir"]
    assert v.datos["totales"]["minutos"] == {
        "programadas": 420,
        "exigibles": 420,
        "cumplidas": 195,
        "faltantes": 30,
        "justificadas": 75,
        "pendientes": 120,
        "suspendidas": 0,
    }
    assert not errores
    qtbot.wait(50)
    ventana.grab().save(str(ruta / "03-asistencia-corregida.png"))
    for formato in ("pdf", "xlsx"):
        assert v.exportar_a(ruta / f"asistencia-ficticia.{formato}", formato)
    with pymupdf.open(ruta / "asistencia-ficticia.pdf") as pdf:
        for i, pagina in enumerate(pdf):
            pixmap = pagina.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6))
            pixmap.save(ruta / f"04-reporte-pdf-{i + 1}.png")
    libro = load_workbook(ruta / "asistencia-ficticia.xlsx")
    resumen = libro["Resumen de horas"]
    assert resumen["B4"].value == 195
    tabla = QTableWidget(resumen.max_row, resumen.max_column)
    qtbot.addWidget(tabla)
    tabla.resize(950, 550)
    tabla.setWindowTitle("Resumen de horas exportado a Excel (datos ficticios)")
    for i, fila in enumerate(resumen.iter_rows(values_only=True)):
        for j, valor in enumerate(fila):
            tabla.setItem(i, j, QTableWidgetItem(str(valor) if valor is not None else ""))
    tabla.resizeColumnsToContents()
    tabla.show()
    qtbot.wait(30)
    tabla.grab().save(str(ruta / "05-excel-resumen.png"))
