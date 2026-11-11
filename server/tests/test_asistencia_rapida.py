"""Registro rápido de asistencia por hora (cuatro botones por fila) contra la API real y
PostgreSQL de pruebas. Datos ficticios: tres horas del lunes 2026-11-02."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import QApplication
from test_interfaz_asistencia_hora import abrir, api_horas, errores_horas  # noqa: F401

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.theme.estilos import hoja_de_estilo
from asi_cliente.views import asistencia_hora as vista_horas
from asi_cliente.views.asistencia_rapida import llegada_sugerida
from asi_cliente.views.ventana_principal import VentanaPrincipal

pytest_plugins = ["server.tests.test_asistencia_hora"]
FECHA = "2026-11-02"


def en_servidor(api):  # noqa: F811
    return api.get("/bitacora/horas", fecha=FECHA)["filas"]


def tarjetas(v):
    return {clave: t.valor.text() for clave, t in v.tarjetas.items()}


def procesar():
    for _ in range(4):
        QApplication.processEvents()


# --- pantalla y resumen -----------------------------------------------------------------


def test_una_fila_por_hora_con_cuatro_botones_y_resumen_real(qtbot, api_horas, errores_horas):  # noqa: F811
    v = abrir(qtbot, api_horas)
    assert v.modos.currentIndex() == 0  # se abre en «Registro rápido»
    assert len(v.filas_rapidas) == 3
    for fila in v.filas_rapidas:
        assert list(fila.botones) == ["asistio", "retardo", "falto", "justificado"]
        assert not any(b.isChecked() for b in fila.botones.values())  # nada se marca solo
        assert fila.chip.text() == "Pendiente"
    horas = [f.fila["programado_inicio"] for f in v.filas_rapidas]
    assert horas == sorted(horas)  # ordenadas por hora
    assert tarjetas(v) == {
        "programadas": "3 h",
        "cumplidas": "0 h",
        "retardo": "0",
        "falto": "0",
        "pendiente": "3",
    }
    assert errores_horas == []


# --- registro con un clic -------------------------------------------------------------


def test_asistio_y_falta_con_un_clic_se_guardan_en_postgresql(qtbot, api_horas, errores_horas):  # noqa: F811
    v = abrir(qtbot, api_horas)
    primera, segunda = v.filas_rapidas[0], v.filas_rapidas[1]
    primera.botones["asistio"].click()
    segunda.botones["falto"].click()
    # Se guardó en el servidor, sin ventanas y sin recargar la lista.
    servidor = en_servidor(api_horas)
    assert [f["estado"] for f in servidor[:2]] == ["asistio", "falto"]
    assert v.filas_rapidas[0] is primera
    assert primera.botones["asistio"].isChecked() and primera.chip.text() == "Asistió"
    assert primera.aviso.text().startswith("✓ Guardado: Asistió")
    assert tarjetas(v)["cumplidas"] == "1 h"
    assert tarjetas(v)["falto"] == "1" and tarjetas(v)["pendiente"] == "1"
    # Volver a pulsar el mismo estado no crea nada ni pide motivo.
    primera.botones["asistio"].click()
    assert primera.estado_editor is None
    # Se conserva al volver a abrir la pantalla.
    otra = abrir(qtbot, api_horas)
    assert [f.fila["estado"] for f in otra.filas_rapidas] == ["asistio", "falto", "pendiente"]
    assert errores_horas == []


def test_retardo_pide_la_hora_real_en_la_misma_fila(qtbot, api_horas, errores_horas):  # noqa: F811
    v = abrir(qtbot, api_horas)
    fila = v.filas_rapidas[2]  # 09:00–10:00
    fila.botones["retardo"].click()
    assert fila.estado_editor == "retardo" and not fila.entrada.isHidden()
    assert en_servidor(api_horas)[2]["estado"] == "pendiente"  # aún no se guarda
    assert v.cambios_pendientes
    fila.entrada.setTime(QTime(9, 10))
    qtbot.keyClick(fila, Qt.Key_Return)  # Enter guarda
    registro = en_servidor(api_horas)[2]["asistencia"]
    assert registro["estado"] == "retardo" and registro["hora_entrada"] == "09:10:00"
    assert registro["minutos_cumplidos"] == 50
    assert not v.cambios_pendientes
    assert tarjetas(v)["retardo"] == "1"
    assert errores_horas == []


def test_llegada_sugerida_dentro_del_tramo():
    fila = {
        "fecha": FECHA,
        "programado_inicio": "09:00:00",
        "programado_fin": "10:00:00",
        "tolerancia_minutos": 10,
    }
    from datetime import date, datetime

    # Otro día: inicio + tolerancia + 1 minuto.
    assert llegada_sugerida(fila, date(2026, 11, 3), datetime(2026, 11, 3, 9, 30)) == QTime(9, 11)
    # Clase en curso hoy: la hora actual.
    hoy = date(2026, 11, 2)
    assert llegada_sugerida(fila, hoy, datetime(2026, 11, 2, 9, 25)) == QTime(9, 25)
    # Nunca fuera del tramo.
    assert llegada_sugerida(fila, hoy, datetime(2026, 11, 2, 11, 0)) == QTime(9, 11)
    assert llegada_sugerida({**fila, "tolerancia_minutos": 90}, hoy, datetime(2026, 11, 2, 8)) == (
        QTime(9, 59)
    )


def test_justificado_exige_motivo_y_permite_adjuntar_justificante(
    qtbot,
    api_horas,  # noqa: F811
    errores_horas,  # noqa: F811
):
    v = abrir(qtbot, api_horas)
    fila = v.filas_rapidas[0]
    fila.botones["justificado"].click()
    fila.guardar_editor()  # sin motivo
    assert "motivo" in fila.aviso.text().lower()
    assert en_servidor(api_horas)[0]["estado"] == "pendiente"
    fila.motivo_justificacion.setText("Comisión oficial ficticia")
    fila.guardar_editor()
    registro = en_servidor(api_horas)[0]["asistencia"]
    assert registro["estado"] == "justificado"
    assert registro["justificacion"] == "Comisión oficial ficticia"
    assert registro["minutos_justificados"] == 60
    assert not fila.boton_justificante.isHidden()  # vínculo con el archivo digital
    abiertos = []
    v.abrir_documentos_de = lambda f: abiertos.append(f["asistencia"]["id"])
    fila.boton_justificante.click()
    assert abiertos == [registro["id"]]
    assert errores_horas == []


# --- correcciones y observaciones --------------------------------------------------------


def test_corregir_un_estado_pide_motivo_y_queda_en_el_historial(qtbot, api_horas, errores_horas):  # noqa: F811
    v = abrir(qtbot, api_horas)
    fila = v.filas_rapidas[0]
    fila.botones["asistio"].click()
    fila.botones["falto"].click()  # cambio de estado: corrección
    assert fila.estado_editor == "falto" and not fila.motivo_correccion.isHidden()
    fila.guardar_editor()  # sin motivo
    assert en_servidor(api_horas)[0]["estado"] == "asistio"
    assert "motivo" in fila.aviso.text().lower()
    fila.motivo_correccion.setText("Se registró por error")
    fila.guardar_editor()
    registro = en_servidor(api_horas)[0]["asistencia"]
    assert registro["estado"] == "falto" and registro["correcciones"] == 1
    historial = api_horas.get(f"/asistencias/horas/{registro['id']}/historial")
    assert [h["accion"] for h in historial] == ["registrar", "corregir"]
    assert historial[-1]["despues"]["motivo"] == "Se registró por error"
    assert fila.aviso.text().startswith("✓ Corrección guardada")
    # Cancelar un cambio deja todo como estaba.
    fila.botones["asistio"].click()
    fila.boton_cancelar.click()
    assert fila.botones["falto"].isChecked() and not fila.botones["asistio"].isChecked()
    assert errores_horas == []


def test_observacion_por_registro(qtbot, api_horas, errores_horas):  # noqa: F811
    v = abrir(qtbot, api_horas)
    pendiente, registrada = v.filas_rapidas[1], v.filas_rapidas[0]
    # En una hora pendiente se guarda junto con el registro.
    pendiente.boton_nota.click()
    pendiente.observacion.setText("Llegó con el grupo")
    pendiente.observacion.setModified(True)
    assert v.cambios_pendientes
    pendiente.botones["asistio"].click()
    assert en_servidor(api_horas)[1]["asistencia"]["observaciones"] == "Llegó con el grupo"
    # En una ya registrada, Enter la guarda (con su registro en la auditoría).
    registrada.botones["falto"].click()
    registrada.mostrar_observacion()
    registrada.observacion.setText("Avisó por correo")
    registrada.observacion.setModified(True)
    registrada.guardar_observacion()
    asistencia = en_servidor(api_horas)[0]["asistencia"]
    assert asistencia["observaciones"] == "Avisó por correo" and asistencia["estado"] == "falto"
    assert not v.cambios_pendientes
    assert errores_horas == []


# --- cambios sin guardar, duplicados y permisos ----------------------------------------------


def test_avisa_de_datos_sin_guardar(qtbot, api_horas, monkeypatch, errores_horas):  # noqa: F811
    ventana = VentanaPrincipal(api_horas.usuario, api_horas)
    qtbot.addWidget(ventana)
    v = ventana.abrir_seccion("Asistencia por hora")
    v.fecha.setDate(QDate(2026, 11, 2))
    v.filas_rapidas[0].botones["retardo"].click()
    assert ventana.cambios_sin_guardar() == ["Asistencia por hora: datos escritos sin guardar"]
    # Cambiar de fecha pregunta; si no se acepta, la fecha no cambia.
    monkeypatch.setattr(vista_horas, "confirmar", lambda *_a, **_k: False)
    v.fecha.setDate(QDate(2026, 11, 3))
    assert v.fecha.date() == QDate(2026, 11, 2) and v.filas_rapidas[0].estado_editor
    v.filas_rapidas[0].cerrar_editor()
    assert ventana.cambios_sin_guardar() == []
    assert errores_horas == []


def test_no_duplica_si_otra_pantalla_ya_registro(qtbot, api_horas, errores_horas):  # noqa: F811
    una, otra = abrir(qtbot, api_horas), abrir(qtbot, api_horas)
    una.filas_rapidas[0].botones["asistio"].click()
    fila = otra.filas_rapidas[0]  # aún muestra la hora como pendiente
    fila.botones["falto"].click()
    assert fila.aviso.text().startswith("No se guardó")
    registros = [f for f in en_servidor(api_horas) if f["asistencia"]]
    assert len(registros) == 1 and registros[0]["estado"] == "asistio"
    assert errores_horas == []  # el aviso aparece en la fila, sin ventana emergente


def test_consulta_ve_pero_no_registra(qtbot, api_horas, consulta, errores_horas):  # noqa: F811
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(consulta.correo, "contrasena-de-prueba")
    v = abrir(qtbot, api)
    fila = v.filas_rapidas[0]
    assert all(b.isHidden() for b in fila.botones.values())
    fila.elegir("asistio")
    assert en_servidor(api_horas)[0]["estado"] == "pendiente"
    assert errores_horas == []


# --- filtros y búsqueda ----------------------------------------------------------------------


def test_busqueda_y_filtros_al_instante(qtbot, api_horas, errores_horas):  # noqa: F811
    v = abrir(qtbot, api_horas)
    v.show()
    nombre = v.filas_rapidas[0].fila["docente_nombre"]
    v.buscar.setText(nombre.lower()[:8])  # minúsculas y parcial
    assert len(v.filas_visibles()) >= 1
    v.buscar.setText("nadie con este nombre")
    assert v.filas_visibles() == [] and not v.vacio.isHidden()
    assert tarjetas(v)["programadas"] == "0 h"
    v.buscar.clear()
    for combo in (v.grupo, v.aula):
        if combo.count() > 1:
            combo.setCurrentIndex(1)
            valor = combo.currentData()
            campo = "grupo" if combo is v.grupo else "aula"
            assert v.filas_visibles() and all(f[campo] == valor for f in v.filas_visibles())
            combo.setCurrentIndex(0)
    v.estado.setCurrentIndex(v.estado.findData("pendiente"))  # filtro de estado
    assert all(f["estado"] == "pendiente" for f in v.filas_visibles())
    v.limpiar_filtros()
    assert len(v.filas_visibles()) == 3
    assert errores_horas == []


# --- resoluciones ---------------------------------------------------------------------------


@pytest.mark.parametrize(("ancho", "alto"), [(1024, 700), (1366, 768), (1920, 1080)])
def test_botones_completos_en_distintas_resoluciones(qtbot, api_horas, errores_horas, ancho, alto):  # noqa: F811
    QApplication.instance().setStyleSheet(hoja_de_estilo("claro"))
    try:
        v = abrir(qtbot, api_horas)
        v.resize(ancho, alto)
        v.show()
        qtbot.waitExposed(v)
        procesar()
        for fila in v.filas_rapidas:
            for b in fila.botones.values():
                assert b.width() >= b.sizeHint().width(), (ancho, b.text())  # sin recortes
            # La fila cabe a lo ancho: no hay que desplazarse de lado.
            assert fila.width() <= v.lista.viewport().width()
        assert v.lista.horizontalScrollBar().maximum() == 0
        carpeta = os.environ.get("ASI_REVISION_VISUAL_DIR")
        if carpeta:
            v.filas_rapidas[0].botones["asistio"].click()
            v.filas_rapidas[1].botones["retardo"].click()
            procesar()
            v.grab().save(str(Path(carpeta) / f"asistencia_rapida_{ancho}x{alto}.png"))
    finally:
        QApplication.instance().setStyleSheet("")
    assert errores_horas == []
