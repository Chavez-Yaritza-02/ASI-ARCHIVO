"""Carga, versiones, vista, descarga y vínculos desde Qt contra el servidor ficticio."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QTimer

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.views import documentos as vistas
from asi_cliente.views.documentos import VistaDocumentos
from asi_cliente.views.ventana_principal import VentanaPrincipal
from server.tests.test_asistencia_hora import capturar, ver
from server.tests.test_documentos import pdf_ficticio

pytest_plugins = ["server.tests.test_documentos"]


@pytest.fixture
def api_archivo(admin, almacen_documentos):
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(admin.correo, "contrasena-de-prueba")
    return api


@pytest.fixture
def errores_archivo(monkeypatch):
    errores = []
    monkeypatch.setattr(vistas, "mostrar_error", lambda _p, e: errores.append(str(e)))
    return errores


def responder(monkeypatch, *datos):
    respuestas = list(datos)

    class Formulario:
        def __init__(self, *_a, **_k):
            self.actual = None

        def exec(self):
            if not respuestas:
                return False
            self.actual = respuestas.pop(0)
            return True

        def valores(self):
            return self.actual

    monkeypatch.setattr(vistas, "DialogoFormulario", Formulario)


def test_cargar_ver_descargar_y_nueva_version_desde_pantalla(
    qtbot, api_archivo, monkeypatch, tmp_path, errores_archivo
):
    v = VistaDocumentos(api_archivo, api_archivo.usuario)
    qtbot.addWidget(v)
    origen = tmp_path / "justificante-ficticio.pdf"
    original = pdf_ficticio()
    origen.write_bytes(original)
    monkeypatch.setattr(v, "_archivo", lambda: origen)
    cat = next(c["id"] for c in v.categorias if c["clave"] == "justificante")
    responder(
        monkeypatch,
        {
            "nombre": "Justificante ficticio",
            "fecha": "2026-11-02",
            "categoria_id": cat,
            "descripcion": None,
            "docente_id": None,
            "periodo_id": None,
        },
    )
    v.boton_cargar.click()
    assert len(v.tabla.filas) == 1
    assert v.documento["version_actual"]["numero"] == 1
    v.boton_ver.click()
    assert v.imagen.pixmap() is not None and not v.imagen.pixmap().isNull()
    destino = tmp_path / "descarga-ficticia.pdf"
    assert v.descargar_a(destino) and destino.read_bytes() == original
    origen.write_bytes(pdf_ficticio("Versión dos ficticia"))
    responder(monkeypatch, {"motivo": "Corrección ficticia del documento"})
    v.boton_version.click()
    assert [f["numero"] for f in v.documento["versiones"]] == [2, 1]
    v.versiones.setCurrentIndex(1)
    assert v.descargar_a(destino) and destino.read_bytes() == original
    assert not errores_archivo
    evidencia = os.environ.get("ASI_REVISION_VISUAL_DIR")
    if evidencia:
        v.resize(1400, 1000)
        v.show()
        v.ver()
        qtbot.wait(60)
        v.grab().save(str(Path(evidencia) / "06-archivo-digital.png"))


def test_buscar_editar_archivar_restaurar_desde_interfaz(
    qtbot, api_archivo, monkeypatch, tmp_path, errores_archivo
):
    v = VistaDocumentos(api_archivo, api_archivo.usuario)
    qtbot.addWidget(v)
    ruta = tmp_path / "horario-ficticio.pdf"
    ruta.write_bytes(pdf_ficticio())
    cat = v.categorias[0]["id"]
    r = api_archivo.subir(
        "/documentos",
        ruta.name,
        ruta.read_bytes(),
        {
            "datos": '{"nombre":"Horario ficticio","fecha":"2026-11-02","categoria_id":'
            + str(cat)
            + "}"
        },
    )
    v.buscar()
    v.tabla.selectRow(0)
    responder(
        monkeypatch,
        {
            "nombre": "Horario ficticio corregido",
            "descripcion": "Nota ficticia",
            "fecha": "2026-11-02",
            "categoria_id": cat,
            "docente_id": None,
            "periodo_id": None,
            "motivo": "Corrección ficticia de metadatos",
        },
    )
    v.boton_editar.click()
    assert v.documento["nombre"] == "Horario ficticio corregido"
    v.texto.setText("corregído")
    v.boton_buscar.click()
    assert len(v.tabla.filas) == 1
    v.tabla.selectRow(0)
    responder(monkeypatch, {"motivo": "Archivo ficticio concluido"})
    v.boton_archivar.click()
    assert not v.tabla.filas
    v.archivados.setChecked(True)
    v.boton_buscar.click()
    v.tabla.selectRow(0)
    assert not v.documento["activo"]
    responder(monkeypatch, {"motivo": "Restauración ficticia autorizada"})
    v.boton_archivar.click()
    assert api_archivo.get(f"/documentos/{r['documento_id']}")["activo"]
    assert not errores_archivo


def test_lector_ve_versiones_sin_botones_de_carga_o_descarga(
    qtbot, api_archivo, consulta, almacen_documentos, errores_archivo
):
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(consulta.correo, "contrasena-de-prueba")
    v = VistaDocumentos(api, api.usuario)
    qtbot.addWidget(v)
    assert v.boton_cargar.isHidden() and v.boton_descargar.isHidden()
    assert v.boton_editar.isHidden() and v.boton_archivar.isHidden()
    assert not errores_archivo


def test_vincular_justificante_desde_la_hora_con_version_explicita(
    qtbot, api_archivo, cliente, como_admin, escuela_horas, monkeypatch, errores_archivo
):
    a = capturar(cliente, como_admin, ver(cliente, como_admin)["filas"][0], "falto").json()
    cat = next(
        c["id"] for c in api_archivo.get("/documentos/categorias") if c["clave"] == "justificante"
    )
    import json

    d = api_archivo.subir(
        "/documentos",
        "justificante.pdf",
        pdf_ficticio(),
        {
            "datos": json.dumps(
                {
                    "nombre": "Justificante de hora ficticia",
                    "fecha": "2026-11-02",
                    "categoria_id": cat,
                    "docente_id": a["docente_id"],
                    "periodo_id": a["periodo_id"],
                }
            )
        },
    )
    v = VistaDocumentos(api_archivo, api_archivo.usuario, a)
    qtbot.addWidget(v)
    assert not v.tabla.filas
    v.solo_vinculados.setChecked(False)
    v.boton_buscar.click()
    v.tabla.seleccionar_id(d["documento_id"])
    responder(monkeypatch, {"motivo": "Evidencia ficticia para esta hora"})
    v.boton_vincular.click()
    v.solo_vinculados.setChecked(True)
    v.boton_buscar.click()
    assert len(v.tabla.filas) == 1
    v.tabla.selectRow(0)
    assert v.documento["asistencias"][0]["asistencia_id"] == a["id"]
    responder(monkeypatch, {"motivo": "Rectificación ficticia del vínculo"})
    v.boton_desvincular.click()
    assert not v.tabla.filas
    assert ver(cliente, como_admin)["filas"][0]["estado"] == "falto"
    assert not errores_archivo


def test_menu_integra_documentos(qtbot, api_archivo, errores_archivo):
    ventana = VentanaPrincipal(api_archivo.usuario, api_archivo)
    qtbot.addWidget(ventana)
    assert isinstance(ventana.abrir_seccion("Documentos"), VistaDocumentos)
    assert not errores_archivo


def test_formulario_modal_real_de_carga_y_edicion(
    qtbot, api_archivo, tmp_path, monkeypatch, errores_archivo
):
    v = VistaDocumentos(api_archivo, api_archivo.usuario)
    qtbot.addWidget(v)
    ruta = tmp_path / "modal-ficticio.pdf"
    ruta.write_bytes(pdf_ficticio())
    monkeypatch.setattr(v, "_archivo", lambda: ruta)
    formulario_real = vistas.DialogoFormulario

    def formulario(titulo, campos, valores=None, padre=None):
        d = formulario_real(titulo, campos, valores, padre=padre)
        d.controles["nombre"].setText("Documento de modal ficticio")
        if "motivo" in d.controles:
            d.controles["motivo"].setText("Edición ficticia mediante formulario real")
        evidencia = os.environ.get("ASI_REVISION_VISUAL_DIR")
        if evidencia:
            d.show()
            qtbot.wait(30)
            d.grab().save(str(Path(evidencia) / "07-formulario-documento.png"))
        QTimer.singleShot(100, d._aceptar)
        return d

    monkeypatch.setattr(vistas, "DialogoFormulario", formulario)
    v.boton_cargar.click()
    assert v.documento["nombre"] == "Documento de modal ficticio"
    assert v.documento["descripcion"] == ""
    v.boton_editar.click()
    assert not errores_archivo
