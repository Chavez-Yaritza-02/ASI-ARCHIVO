"""Pantalla de captura horaria real contra FastAPI y PostgreSQL ficticios."""

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QDate, QTime

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.views import asistencia_hora as vista_horas
from asi_cliente.views.asistencia_hora import DialogoAsistenciaHora, VistaAsistenciaHora
from asi_cliente.views.ventana_principal import VentanaPrincipal

pytest_plugins = ["server.tests.test_asistencia_hora"]


@pytest.fixture
def api_horas(admin, escuela_horas):
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(admin.correo, "contrasena-de-prueba")
    return api


@pytest.fixture
def errores_horas(monkeypatch):
    errores = []
    monkeypatch.setattr(vista_horas, "mostrar_error", lambda _p, e: errores.append(e))
    return errores


def abrir(qtbot, api):
    v = VistaAsistenciaHora(api, api.usuario)
    qtbot.addWidget(v)
    v.fecha.setDate(QDate(2026, 11, 2))
    return v


def responder(monkeypatch, datos):
    class Formulario:
        def __init__(self, *_):
            self.pendiente = True

        def exec(self):
            if self.pendiente:
                self.pendiente = False
                return True
            return False

        def datos(self):
            return datos

    monkeypatch.setattr(vista_horas, "DialogoAsistenciaHora", Formulario)


def test_capturar_estados_independientes_y_parcial_en_interfaz(
    qtbot, api_horas, monkeypatch, errores_horas
):
    v = abrir(qtbot, api_horas)
    assert len(v.tabla.filas) == 3
    for i, datos in enumerate(
        [
            {"estado": "asistio"},
            {"estado": "falto"},
            {
                "estado": "parcial",
                "hora_entrada": "09:00",
                "hora_salida": "09:30",
                "minutos_justificados": 30,
                "justificacion": "Permiso ficticio",
            },
        ]
    ):
        v.tabla.selectRow(i)
        responder(monkeypatch, datos)
        v.boton_registrar.click()
    assert [f["estado"] for f in v.tabla.filas] == ["asistio", "falto", "parcial"]
    assert v.datos["totales"]["horas"]["cumplidas"] == 1.5
    assert v.datos["totales"]["horas"]["faltantes"] == 1
    assert v.datos["totales"]["horas"]["justificadas"] == 0.5
    assert errores_horas == []


def test_dialogo_real_permite_parcial_y_minutos_justificados(qtbot, api_horas):
    f = api_horas.get("/bitacora/horas", fecha="2026-11-02")["filas"][0]
    d = DialogoAsistenciaHora(f)
    qtbot.addWidget(d)
    d.estado.setCurrentIndex(d.estado.findData("parcial"))
    assert d.usar_entrada.isChecked() and d.usar_salida.isChecked()
    d.entrada.setTime(QTime(7, 10))
    d.salida.setTime(QTime(7, 40))
    d.minutos_justificados.setValue(20)
    assert d.justificacion.isEnabled()
    d.justificacion.setText("Justificación ficticia")
    datos = d.datos()
    assert datos["estado"] == "parcial" and datos["minutos_justificados"] == 20
    assert datos["hora_entrada"] == "07:10" and datos["hora_salida"] == "07:40"
    d.estado.setCurrentIndex(d.estado.findData("justificado"))
    assert d.datos()["hora_entrada"] is None and d.datos()["hora_salida"] is None


def test_corregir_e_historial_desde_pantalla(qtbot, api_horas, monkeypatch, errores_horas):
    v = abrir(qtbot, api_horas)
    v.tabla.selectRow(0)
    responder(monkeypatch, {"estado": "asistio"})
    v.boton_registrar.click()
    v.tabla.selectRow(0)
    responder(monkeypatch, {"estado": "falto", "motivo": "Corrección ficticia por hora"})
    v.boton_registrar.click()
    assert v.tabla.filas[0]["estado"] == "falto"
    assert v.tabla.filas[0]["asistencia"]["correcciones"] == 1
    cambios = []

    class Historial:
        def __init__(self, datos, *_):
            cambios.extend(datos)

        def exec(self):
            return True

    monkeypatch.setattr(vista_horas, "DialogoHistorial", Historial)
    v.tabla.selectRow(0)
    v.boton_historial.click()
    assert [c["accion"] for c in cambios] == ["registrar", "corregir"]
    assert errores_horas == []


def test_exportaciones_dia_y_rango_desde_pantalla(qtbot, api_horas, tmp_path, errores_horas):
    v = abrir(qtbot, api_horas)
    v.desde.setDate(QDate(2026, 11, 2))
    v.hasta.setDate(QDate(2026, 11, 4))
    for formato, firma in [("pdf", b"%PDF"), ("xlsx", b"PK")]:
        for rango in (False, True):
            ruta = tmp_path / f"horas_{rango}.{formato}"
            assert v.exportar_a(ruta, formato, rango)
            assert ruta.read_bytes().startswith(firma)
    assert errores_horas == []


def test_solo_consulta_no_puede_capturar(qtbot, api_horas, consulta, errores_horas):
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(consulta.correo, "contrasena-de-prueba")
    v = abrir(qtbot, api)
    assert len(v.tabla.filas) == 3
    assert v.boton_registrar.isHidden() and v.boton_pdf.isHidden()
    v.tabla.selectRow(0)
    v.registrar()
    assert v.tabla.filas[0]["asistencia"] is None
    assert errores_horas == []


def test_menu_abre_asistencia_horaria_antes_del_legado(qtbot, api_horas, errores_horas):
    v = VentanaPrincipal(api_horas.usuario, api_horas)
    qtbot.addWidget(v)
    assert v.secciones[0][0] == "Asistencia por hora"
    assert isinstance(v.abrir_seccion("Asistencia por hora"), VistaAsistenciaHora)
    assert "Bitácora del día" in [s[0] for s in v.secciones]
    assert errores_horas == []
