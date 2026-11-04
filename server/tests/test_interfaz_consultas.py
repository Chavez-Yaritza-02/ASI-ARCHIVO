"""Pantallas reales de Etapa 5 contra FastAPI y PostgreSQL con datos ficticios."""

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QDate, QTime

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.views import consultas as vistas
from asi_cliente.views import horarios as vista_horarios
from asi_cliente.views.consultas import (
    VistaBuscador,
    VistaConfiguracionAsistencia,
    VistaGrupos,
    VistaUbicacion,
)
from asi_cliente.views.horarios import VistaHorarios
from asi_cliente.views.ventana_principal import VentanaPrincipal

pytest_plugins = ["server.tests.test_consultas"]


@pytest.fixture
def api_consultas(admin, escuela_consulta):
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(admin.correo, "contrasena-de-prueba")
    return api


@pytest.fixture
def errores_consultas(monkeypatch):
    errores = []
    monkeypatch.setattr(vistas, "mostrar_error", lambda _p, e: errores.append(e))
    monkeypatch.setattr(vista_horarios, "mostrar_error", lambda _p, e: errores.append(e))
    return errores


def test_buscar_y_filtrar_desde_interfaz(qtbot, api_consultas, errores_consultas):
    v = VistaBuscador(api_consultas, api_consultas.usuario)
    qtbot.addWidget(v)
    v.filtros.fecha.setDate(QDate(2026, 11, 2))
    v.texto.setText("cálc")
    v.boton_buscar.click()
    assert any(f["tipo"] == "Materias" for f in v.entidades.filas)
    assert len(v.tabla.filas) == 2
    v.filtros.carrera.setText("OTRA")
    v.boton_buscar.click()
    assert not v.entidades.filas and not v.tabla.filas
    assert not errores_consultas


def test_semana_y_exportaciones_desde_interfaz(
    qtbot, api_consultas, errores_consultas, escuela_consulta, tmp_path
):
    v = VistaGrupos(api_consultas, api_consultas.usuario)
    qtbot.addWidget(v)
    v.filtros.fecha.setDate(QDate(2026, 11, 2))
    v.grupo.setCurrentIndex(v.grupo.findData(escuela_consulta["grupo_a"]))
    v.boton_consultar.click()
    assert len(v.tabla.filas) == 2
    assert "2026-11-02 a 2026-11-08" in v.resumen.text()
    for formato, firma in [("pdf", b"%PDF"), ("xlsx", b"PK")]:
        ruta = tmp_path / f"grupo.{formato}"
        assert v.exportar_a(ruta, formato)
        assert ruta.read_bytes().startswith(firma)
    v.filtros.fecha.setDate(QDate(2026, 11, 9))
    assert v.datos is None and not v.boton_pdf.isEnabled()
    assert not errores_consultas


def test_ubicacion_y_sin_clase_desde_interfaz(
    qtbot, api_consultas, errores_consultas, escuela_consulta
):
    v = VistaUbicacion(api_consultas, api_consultas.usuario)
    qtbot.addWidget(v)
    v.fecha.setDate(QDate(2026, 11, 2))
    v.hora.setTime(QTime(7, 30))
    v.docente.setCurrentIndex(v.docente.findData(escuela_consulta["docente"]))
    v.boton_consultar.click()
    assert v.tabla.filas[0]["aula_programada"] == "M01"
    assert "no confirma presencia física" in v.detalle.text()
    v.hora.setTime(QTime(11, 0))
    v.boton_consultar.click()
    assert not v.tabla.filas and "Sin clase asignada" in v.detalle.text()
    assert not errores_consultas


def test_configurar_tolerancia_y_solo_consulta(qtbot, api_consultas, consulta, errores_consultas):
    v = VistaConfiguracionAsistencia(api_consultas, api_consultas.usuario)
    qtbot.addWidget(v)
    assert v.minutos.value() == 10
    v.minutos.setValue(18)
    v.boton_guardar.click()
    assert api_consultas.get("/configuracion/asistencia")["tolerancia_minutos"] == 18
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(consulta.correo, "contrasena-de-prueba")
    lector = VistaConfiguracionAsistencia(api, api.usuario)
    qtbot.addWidget(lector)
    assert lector.boton_guardar.isHidden() and not lector.minutos.isEnabled()
    grupos = VistaGrupos(api, api.usuario)
    qtbot.addWidget(grupos)
    assert grupos.boton_pdf.isHidden() and grupos.boton_excel.isHidden()
    assert not errores_consultas


def test_confirmar_fechas_reales_desde_interfaz(
    qtbot, api_consultas, escuela_consulta, monkeypatch, errores_consultas
):
    v = VistaHorarios(api_consultas, api_consultas.usuario)
    qtbot.addWidget(v)
    v.docente.setCurrentIndex(
        next(
            i
            for i in range(v.docente.count())
            if v.docente.itemData(i)["id"] == escuela_consulta["docente"]
        )
    )
    v.cargar_versiones()
    respuestas = [
        {"desde": "2026-08-03", "hasta": None, "motivo": "Confirmación mediante evidencia ficticia"}
    ]

    class Formulario:
        def __init__(self, *_a, **_k):
            pass

        def exec(self):
            return bool(respuestas)

        def valores(self):
            return respuestas.pop(0)

    monkeypatch.setattr(vista_horarios, "DialogoFormulario", Formulario)
    v.boton_vigencia.click()
    assert v.horario["vigente_desde"] == "2026-08-03"
    assert "vigencia confirmada" in v.estado.text()
    assert not errores_consultas


def test_menu_abre_las_consultas_integradas(qtbot, api_consultas, errores_consultas):
    v = VentanaPrincipal(api_consultas.usuario, api_consultas)
    qtbot.addWidget(v)
    for nombre, clase in [
        ("Buscador", VistaBuscador),
        ("Horarios por grupo", VistaGrupos),
        ("Ubicación programada", VistaUbicacion),
        ("Tolerancia de retardos", VistaConfiguracionAsistencia),
    ]:
        assert isinstance(v.abrir_seccion(nombre), clase)
    assert not errores_consultas
