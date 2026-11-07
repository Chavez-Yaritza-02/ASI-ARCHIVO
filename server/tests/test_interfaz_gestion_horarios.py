"""Sección "Gestión de horarios" contra la API real, con datos y PDF ficticios."""

import os

import pytest
from fastapi.testclient import TestClient
from horario_ficticio import UNO, pdf_escaneado
from PySide6.QtCore import Qt

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.views import gestion_horarios as vista_gestion
from asi_cliente.views import importacion as vista_importacion
from asi_cliente.views.gestion_horarios import VistaCambios, VistaGestionHorarios
from asi_cliente.views.horarios import VistaHorarios
from asi_cliente.views.importacion import VistaImportacion
from asi_cliente.views.periodos import VistaPeriodos
from asi_cliente.views.ventana_principal import VentanaPrincipal

os.environ["ASI_OCR_PROCESOS"] = "1"
CONTRASENA = "contrasena-de-prueba"  # igual que en conftest.py


def api_de(correo: str) -> ClienteApi:
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(correo, CONTRASENA)
    return api


@pytest.fixture
def api(admin):
    api = api_de(admin.correo)
    p = api.post(
        "/periodos",
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    api.post(f"/periodos/{p['id']}/activar")
    api.post("/docentes", {"nombre": "DOCENTE PRUEBA UNO", "nomina": "ZZX0001"})
    api.post("/asignaturas", {"nombre": "CÁLC. DIF."})
    api.post("/aulas", {"clave": "M01"})
    return api


@pytest.fixture
def silencio(monkeypatch):
    errores: list = []
    for modulo in (vista_gestion, vista_importacion):
        monkeypatch.setattr(modulo, "mostrar_error", lambda _p, e, *_: errores.append(e))
        monkeypatch.setattr(modulo, "confirmar", lambda *_a, **_k: True)
    return errores


def gestion_de(qtbot, api) -> tuple[VentanaPrincipal, VistaGestionHorarios]:
    ventana = VentanaPrincipal(api.usuario, api)
    qtbot.addWidget(ventana)
    return ventana, ventana.abrir_seccion("Gestión de horarios")


def test_menu_tiene_una_sola_seccion_de_horarios(qtbot, api):
    ventana, gestion = gestion_de(qtbot, api)
    titulos = [s[0] for s in ventana.secciones]
    assert "Gestión de horarios" in titulos
    assert not {"Horarios", "Importar horarios", "Periodos"} & set(titulos)
    assert isinstance(gestion, VistaGestionHorarios)
    assert [gestion.pestanas.tabText(i) for i in range(gestion.pestanas.count())] == [
        "Horarios",
        "Importar y revisar",
        "Periodos",
        "Registro de cambios",
    ]
    # Los nombres anteriores siguen abriendo la pantalla correcta (dentro de la sección).
    assert isinstance(ventana.abrir_seccion("Horarios"), VistaHorarios)
    assert isinstance(ventana.abrir_seccion("Importar horarios"), VistaImportacion)
    assert isinstance(ventana.abrir_seccion("Periodos"), VistaPeriodos)
    assert "AGOSTO - DICIEMBRE 2026" in gestion.periodo_activo.text()
    assert not gestion.boton_importar.isHidden() and not gestion.boton_cambiar.isHidden()


def test_boton_importar_abre_el_selector_y_asocia_el_periodo(
    qtbot, api, silencio, monkeypatch, tmp_path
):
    archivo = tmp_path / "uno.pdf"
    archivo.write_bytes(pdf_escaneado(UNO))
    titulos: list[str] = []

    def selector(_padre, titulo, _carpeta, filtro):
        titulos.append(titulo)
        assert "*.zip" in filtro and "*.pdf" in filtro
        return str(archivo), filtro

    monkeypatch.setattr(vista_importacion.QFileDialog, "getOpenFileName", selector)
    _ventana, gestion = gestion_de(qtbot, api)
    qtbot.mouseClick(gestion.boton_importar, Qt.LeftButton)

    assert titulos == ["Elegir horarios para AGOSTO - DICIEMBRE 2026"]
    assert gestion.pestanas.tabText(gestion.pestanas.currentIndex()) == "Importar y revisar"
    lotes = api.get("/importaciones")
    assert len(lotes) == 1 and lotes[0]["periodo"]["nombre"] == "AGOSTO - DICIEMBRE 2026"
    # Vista previa editable de la página leída por OCR.
    vista = gestion.importacion
    vista.cargar_importacion()
    assert vista.pagina is not None and vista.cuadricula.rowCount() > 0
    assert silencio == []


def test_consulta_solo_visualiza(qtbot, consulta, api):
    lector = api_de(consulta.correo)
    _ventana, gestion = gestion_de(qtbot, lector)
    assert gestion.boton_importar.isHidden() and gestion.boton_cambiar.isHidden()
    pestanas = [gestion.pestanas.tabText(i) for i in range(gestion.pestanas.count())]
    assert pestanas == ["Horarios", "Periodos", "Registro de cambios"]
    assert gestion.horarios.boton_nueva.isHidden()
    assert gestion.periodos.boton_nuevo.isHidden()
    assert "AGOSTO - DICIEMBRE 2026" in gestion.periodo_activo.text()


def test_cambiar_periodo_activo_conserva_el_anterior(qtbot, api, silencio, monkeypatch):
    enero = api.post(
        "/periodos",
        {"nombre": "Enero - Junio 2027", "fecha_inicio": "2027-01-15", "fecha_fin": "2027-06-30"},
    )
    monkeypatch.setattr(vista_gestion.DialogoCambiarPeriodo, "exec", lambda self: True)
    _ventana, gestion = gestion_de(qtbot, api)
    gestion.cambiar_periodo()

    assert silencio == []
    assert "ENERO - JUNIO 2027" in gestion.periodo_activo.text()
    estados = {p["nombre"]: p["estado"] for p in api.get("/periodos")}
    assert estados == {"AGOSTO - DICIEMBRE 2026": "cerrado", "ENERO - JUNIO 2027": "activo"}
    assert api.get("/periodos/activo")["id"] == enero["id"]


def test_sin_periodo_nuevo_lleva_a_crearlo(qtbot, api, silencio):
    _ventana, gestion = gestion_de(qtbot, api)
    gestion.cambiar_periodo()
    assert "No hay periodos nuevos" in str(silencio[0])
    assert gestion.pestanas.tabText(gestion.pestanas.currentIndex()) == "Periodos"


def test_registro_de_cambios_muestra_las_ediciones(qtbot, api):
    periodo = api.get("/periodos/activo")
    docente = api.get("/docentes")[0]
    asignatura = api.get("/asignaturas")[0]
    h = api.post("/horarios", {"docente_id": docente["id"], "periodo_id": periodo["id"]})
    api.put(
        f"/horarios/{h['id']}/bloques",
        [
            {
                "dia": "lunes",
                "hora_inicio": "09:00",
                "hora_fin": "10:00",
                "asignatura_id": asignatura["id"],
                "grupo_letra": "A",
            }
        ],
    )
    _ventana, gestion = gestion_de(qtbot, api)
    vista = gestion.mostrar("Registro de cambios")
    assert isinstance(vista, VistaCambios)
    vista.recargar()
    assert vista.tabla.rowCount() == 2
    cambios = {vista.tabla.item(f, 4).text() for f in range(2)}
    assert cambios == {"Creó la versión", "Editó las horas"}
