"""Pantalla de importación contra la API real, con PDFs ficticios y OCR real."""

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from horario_ficticio import UNO, Clase, pdf_escaneado

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.cuadricula import DIAS, HORAS
from asi_cliente.views import importacion as vista_importacion
from asi_cliente.views.importacion import DialogoCeldaImportada, VistaImportacion, estado_celda
from asi_cliente.views.ventana_principal import VentanaPrincipal

os.environ["ASI_OCR_PROCESOS"] = "1"
CONTRASENA = "contrasena-de-prueba"  # igual que en conftest.py

# UNO con una materia que no está en el catálogo y un aula mal leída ("MOS" ~ M05).
DOCUMENTO = replace(
    UNO,
    clases=[
        Clase(0, 7, "CALC. DIF.", "A", "M01"),
        Clase(2, 7, "FIS. GRAL", "B", "MOS"),
    ],
)


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
    for aula in ("M01", "M05"):
        api.post("/aulas", {"clave": aula})
    return api


@pytest.fixture
def silencio(monkeypatch):
    errores: list = []
    monkeypatch.setattr(vista_importacion, "mostrar_error", lambda _p, e, *_: errores.append(e))
    monkeypatch.setattr(vista_importacion, "confirmar", lambda *_a, **_k: True)
    monkeypatch.setattr(vista_importacion.QMessageBox, "information", lambda *_a, **_k: None)
    return errores


def texto(vista, dia, hora) -> str:
    item = vista.cuadricula.item(HORAS.index(hora), DIAS.index(dia))
    return item.text() if item else ""


def test_importar_revisar_y_aprobar_desde_la_pantalla(qtbot, api, silencio, monkeypatch, tmp_path):
    archivo = tmp_path / "uno.pdf"
    archivo.write_bytes(pdf_escaneado(DOCUMENTO))
    original = archivo.read_bytes()

    vista = VistaImportacion(api, api.usuario)
    qtbot.addWidget(vista)
    vista.importar_archivo(archivo, vista.periodo.currentData()["id"])
    assert archivo.read_bytes() == original  # el original no se modifica
    assert vista.importacion["estado"] == "en_revision"
    assert vista.pagina["docente"]["nombre"] == "DOCENTE PRUEBA UNO"

    # Colores: lo que coincide está listo (salvo el grupo, que es solo una letra).
    assert estado_celda(vista.celdas[("lunes", 7)]) == "grupo"
    assert estado_celda(vista.celdas[("miercoles", 7)]) == "falta"  # FIS. GRAL no existe
    assert "«FIS. GRAL»" in texto(vista, "miercoles", 7)
    assert not vista.boton_guardar.isEnabled()

    # El usuario crea la materia y revisa la celda (el aula sugerida M05 queda aceptada).
    fisica = api.post("/asignaturas", {"nombre": "FIS. GRAL"})
    vista.catalogos["asignaturas"].append(fisica)

    class Revisada:
        ELIMINAR = DialogoCeldaImportada.ELIMINAR

        def __init__(self, _api, _cat, celda, *_a):
            self.celda = {
                **celda,
                "asignatura_id": fisica["id"],
                "confirmar": True,
                "asignatura_estado": "confirmado",
                "aula_estado": "confirmado",
            }

        def exec(self):
            return 1

    monkeypatch.setattr(vista_importacion, "DialogoCeldaImportada", Revisada)
    vista.editar_celda(HORAS.index(7), DIAS.index("miercoles"))
    assert vista.boton_guardar.isEnabled()
    vista.boton_guardar.click()
    assert silencio == []
    assert vista.pagina["lista_pendientes"] == []
    assert "FIS. GRAL" in texto(vista, "miercoles", 7) and "M05" in texto(vista, "miercoles", 7)

    vista.boton_aprobar.click()
    assert silencio == []
    assert vista.pagina["estado"] == "aprobada"
    horarios = api.get("/horarios")
    assert [(h["estado"], h["origen"], h["horas"]) for h in horarios] == [("borrador", "pdf", 2)]


def test_no_aprueba_si_falta_revisar(qtbot, api, silencio, tmp_path):
    archivo = tmp_path / "uno.pdf"
    archivo.write_bytes(pdf_escaneado(DOCUMENTO))
    vista = VistaImportacion(api, api.usuario)
    qtbot.addWidget(vista)
    vista.importar_archivo(archivo, vista.periodo.currentData()["id"])
    assert "Falta revisar" in vista.lista_pendientes.text()
    vista.boton_aprobar.click()
    assert silencio and silencio[0].problemas
    assert api.get("/horarios") == []


def test_consulta_no_ve_la_importacion(qtbot, consulta):
    api = api_de(consulta.correo)
    ventana = VentanaPrincipal(api.usuario, api)
    qtbot.addWidget(ventana)
    assert "Importar horarios" not in [s[0] for s in ventana.secciones]
