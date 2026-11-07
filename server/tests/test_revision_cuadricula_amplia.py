"""Importar horarios › Revisar: cuadrícula a todo el espacio, pendientes ocultables,
selector de páginas, botones en dos filas, «Ampliar» y «Ver PDF original».

Todo con horarios ficticios; los PDF se leen de una carpeta temporal y no se suben a otro
lugar que no sea la API de pruebas.
"""

import os
from dataclasses import replace

import pytest
from horario_ficticio import DOS, UNO, Clase, pdf_escaneado, zip_con
from PySide6.QtWidgets import QApplication
from test_interfaz_navegacion import api  # noqa: F401

from asi_cliente import visor_pdf
from asi_cliente.cuadricula import HORAS, fila_visible_completa
from asi_cliente.views import importacion as vista_importacion
from asi_cliente.views.importacion import DialogoCeldaImportada, VistaImportacion

os.environ["ASI_OCR_PROCESOS"] = "1"

TRES_CLASES = replace(
    UNO,
    clases=[
        Clase(0, 7, "CALC. DIF.", "A", "M01"),
        Clase(2, 8, "CALC. DIF.", "A", "M01"),
        Clase(4, 9, "CALC. DIF.", "A", "M01"),
    ],
)
COMPLETO = replace(  # de 07:00 a 22:00: todo el día
    UNO,
    clases=[Clase(d % 6, h, "CALC. DIF.", "A", "M01") for d, h in enumerate(range(7, 23))],
)


def _procesar():
    for _ in range(4):
        QApplication.processEvents()


@pytest.fixture
def importar(api, tmp_path):  # noqa: F811
    def hacer(nombre, contenido, alto=800, ancho=1280):
        ruta = tmp_path / nombre
        ruta.write_bytes(contenido)
        vista = VistaImportacion(api, api.usuario)
        vista.resize(ancho, alto)
        vista.show()
        vista.importar_archivo(ruta, vista.periodo.currentData()["id"])
        _procesar()
        return vista, ruta

    return hacer


@pytest.fixture
def sin_dialogos(monkeypatch):
    errores = []
    monkeypatch.setattr(vista_importacion, "mostrar_error", lambda _p, e, *_: errores.append(e))
    monkeypatch.setattr(vista_importacion, "confirmar", lambda *_a, **_k: True)
    return errores


# --- 1. Cuadrícula a todo el espacio ----------------------------------------------------------


@pytest.mark.parametrize(("ancho", "alto"), [(1100, 1000), (1440, 1100), (1920, 1200)])
def test_horario_cabe_completo_sin_desplazarse(qtbot, importar, ancho, alto):
    vista, _ = importar("tres.pdf", pdf_escaneado(TRES_CLASES), alto, ancho)
    qtbot.addWidget(vista)
    tabla = vista.cuadricula
    assert tabla.verticalScrollBar().maximum() == 0  # todo el día a la vista
    # Las filas llenan el alto disponible (no queda un hueco debajo de la tabla).
    total = sum(tabla.rowHeight(i) for i in range(tabla.rowCount()))
    assert total == tabla.viewport().height()
    # La tabla ocupa casi todo el ancho de la pantalla (ya no hay columna de páginas).
    assert tabla.width() >= 0.6 * vista.width()


@pytest.mark.parametrize(("ancho", "alto"), [(960, 640), (1024, 720), (1280, 800)])
def test_ventanas_chicas_muestran_las_clases_completas(qtbot, importar, ancho, alto):
    vista, _ = importar("tres.pdf", pdf_escaneado(TRES_CLASES), alto, ancho)
    qtbot.addWidget(vista)
    for hora in (7, 8, 9):
        assert fila_visible_completa(vista.cuadricula, HORAS.index(hora)), (hora, alto)


def test_dia_completo_y_redimensionar(qtbot, importar):
    vista, _ = importar("completo.pdf", pdf_escaneado(COMPLETO), 700, 1100)
    qtbot.addWidget(vista)
    tabla = vista.cuadricula
    assert tabla.verticalScrollBar().maximum() > 0  # no cabe: se desplaza
    assert fila_visible_completa(tabla, 0)
    vista.resize(1600, 1300)
    _procesar()
    if tabla.verticalScrollBar().maximum() == 0:  # al agrandar, vuelve a caber
        assert sum(tabla.rowHeight(i) for i in range(16)) == tabla.viewport().height()
    for i in range(16):
        assert tabla.rowHeight(i) >= 24


# --- 2. Pendientes: solo si hay, y se pueden ocultar --------------------------------------------


def test_pendientes_se_ocultan_y_desaparecen_sin_pendientes(qtbot, importar, monkeypatch, api):  # noqa: F811
    vista, _ = importar("pend.pdf", pdf_escaneado(TRES_CLASES))
    qtbot.addWidget(vista)
    assert vista.columna_pendientes.isVisible()  # hay grupos por validar (solo la letra)
    assert vista.boton_pendientes.text().startswith("Pendientes (")
    ancho_con_lista = vista.cuadricula.width()
    vista.boton_pendientes.click()
    _procesar()
    assert not vista.columna_pendientes.isVisible()
    assert vista.cuadricula.width() > ancho_con_lista  # la cuadrícula usa ese espacio
    vista.boton_pendientes.click()
    _procesar()
    assert vista.columna_pendientes.isVisible()

    # Se resuelven todos: la lista desaparece y el botón lo indica.
    grupo = api.get("/grupos")[0]
    vista.catalogos["grupos"] = api.get("/grupos")

    class Elige:
        ELIMINAR = DialogoCeldaImportada.ELIMINAR

        def __init__(self, _a, _c, celda, *_x):
            self.celda = {**celda, "grupo_id": grupo["id"], "grupo_letra": None}

        def exec(self):
            return 1

    monkeypatch.setattr(vista_importacion, "DialogoCeldaImportada", Elige)
    monkeypatch.setattr(vista_importacion, "preguntar_correccion_repetida", lambda *_: "todas")
    vista.editar_celda(HORAS.index(7), 0)
    assert vista._pendientes_por_tipo()["Grupos"] == []
    assert not vista.columna_pendientes.isVisible()
    assert not vista.boton_pendientes.isEnabled()
    assert vista.boton_pendientes.text() == "Sin pendientes"


# --- 3. Selector de páginas ---------------------------------------------------------------------


def test_selector_con_nombres_completos(qtbot, importar):
    otra = replace(DOS, clases=[Clase(1, 10, "CALC. DIF.", "A", "M01")])
    vista, _ = importar(
        "dos.zip", zip_con({"uno.pdf": pdf_escaneado(UNO), "dos.pdf": pdf_escaneado(otra)})
    )
    qtbot.addWidget(vista)
    selector = vista.paginas
    assert selector.count() == 2
    textos = [selector.itemText(i) for i in range(2)]
    assert any("DOCENTE PRUEBA UNO" in t and "página 1" in t for t in textos)
    assert all("Por revisar" in t for t in textos)
    # El texto se ve completo: el selector es al menos tan ancho como el nombre más largo.
    metricas = selector.fontMetrics()
    assert selector.width() >= max(metricas.horizontalAdvance(t) for t in textos)
    otro = 1 - selector.currentIndex()
    selector.setCurrentIndex(otro)
    assert vista.pagina["id"] == selector.itemData(otro)


# --- 4. Botones en dos filas sin cortar texto -------------------------------------------------


@pytest.mark.parametrize("ancho", [960, 1280, 1920])
def test_botones_en_dos_filas_sin_recortes(qtbot, importar, ancho):
    vista, _ = importar("tres.pdf", pdf_escaneado(TRES_CLASES), 760, ancho)
    qtbot.addWidget(vista)
    herramientas = [
        vista.boton_sugerencias,
        vista.boton_deshacer,
        vista.boton_pendientes,
        vista.boton_ampliar,
        vista.boton_pdf,
    ]
    decisiones = [
        vista.boton_descartar,
        vista.boton_restaurar,
        vista.boton_guardar,
        vista.boton_aprobar,
    ]
    for b in herramientas + decisiones:
        assert b.isVisible()
        assert b.width() >= b.sizeHint().width(), b.text()  # texto completo
    assert len({b.y() for b in herramientas}) == 1
    assert len({b.y() for b in decisiones}) == 1
    assert decisiones[0].y() > herramientas[0].y()  # segunda fila
    # «Ampliar» y «Ver PDF original», lado a lado.
    assert vista.boton_pdf.x() > vista.boton_ampliar.x()
    assert vista.boton_pdf.y() == vista.boton_ampliar.y()


# --- 5. Ampliar y Ver PDF original -------------------------------------------------------------


def test_ampliar_a_pantalla_completa_y_volver(qtbot, importar):
    vista, _ = importar("tres.pdf", pdf_escaneado(TRES_CLASES))
    qtbot.addWidget(vista)
    vista.boton_ampliar.click()
    dialogo = vista._ampliado
    assert dialogo is not None and dialogo.isFullScreen()
    assert vista.panel.window() is dialogo
    assert vista.boton_ampliar.text() == "Salir de pantalla completa"
    _procesar()
    assert fila_visible_completa(vista.cuadricula, HORAS.index(7))
    vista.boton_ampliar.click()  # salir
    _procesar()
    assert vista._ampliado is None
    assert vista.panel.window() is vista.window()
    assert vista.boton_ampliar.text() == "Ampliar"


def test_ver_pdf_original_del_archivo_importado(qtbot, importar):
    vista, _ = importar("tres.pdf", pdf_escaneado(TRES_CLASES))
    qtbot.addWidget(vista)
    assert vista.pagina["documento_sha256"]
    vista.boton_pdf.click()  # el archivo se recuerda al importarlo: no pregunta
    visor = vista.visor
    qtbot.addWidget(visor)
    assert visor.isVisible() and visor.documento.pageCount() == 1
    assert "verificado" in visor.findChildren(vista_importacion.QLabel)[0].text()


def test_ver_pdf_dentro_de_un_zip_elegido_a_mano(
    qtbot, importar, monkeypatch, tmp_path, sin_dialogos
):
    otra = replace(DOS, clases=[Clase(1, 10, "CALC. DIF.", "A", "M01")])
    contenido = zip_con({"uno.pdf": pdf_escaneado(UNO), "dos.pdf": pdf_escaneado(otra)})
    vista, ruta = importar("lote.zip", contenido)
    qtbot.addWidget(vista)
    visor_pdf._RUTAS.clear()  # como en otra sesión: hay que indicar dónde está
    equivocado = tmp_path / "otro.pdf"
    equivocado.write_bytes(pdf_escaneado(DOS))
    elecciones = iter([str(equivocado), str(ruta)])
    monkeypatch.setattr(
        vista_importacion.QFileDialog,
        "getOpenFileName",
        lambda *_a, **_k: (next(elecciones), ""),
    )
    vista.ver_pdf()
    assert len(sin_dialogos) == 1 and "no contiene" in str(sin_dialogos[0])  # rechaza el otro
    assert vista.visor.isVisible()
    qtbot.addWidget(vista.visor)


def test_buscar_pdf_sin_huella_usa_el_nombre(tmp_path):
    ruta = tmp_path / "VIEJO.pdf"
    ruta.write_bytes(pdf_escaneado(UNO))
    datos, verificado = visor_pdf.buscar_pdf(ruta, None, "VIEJO.pdf")
    assert datos == ruta.read_bytes() and verificado is False
    with pytest.raises(visor_pdf.ArchivoNoCoincide):
        visor_pdf.buscar_pdf(ruta, "0" * 64, "VIEJO.pdf")


VESPERTINO = replace(
    UNO,
    clases=[
        Clase(0, 17, "CALC. DIF.", "A", "M01"),
        Clase(0, 18, "CALC. DIF.", "A", "M01"),
        Clase(3, 19, "CALC. DIF.", "A", "M01"),
        Clase(4, 20, "CALC. DIF.", "A", "M01"),
    ],
)


@pytest.mark.parametrize(("ancho", "alto"), [(1100, 760), (1440, 1000), (1920, 1080)])
def test_horario_vespertino_completo_y_horas_legibles(qtbot, importar, ancho, alto):
    vista, _ = importar("tarde.pdf", pdf_escaneado(VESPERTINO), alto, ancho)
    qtbot.addWidget(vista)
    tabla = vista.cuadricula
    for hora in (17, 18, 19, 20):  # de la primera a la última clase, todas completas
        assert fila_visible_completa(tabla, HORAS.index(hora)), (hora, alto)
    encabezado = tabla.verticalHeader()
    for i in range(tabla.rowCount()):  # ninguna hora queda recortada, aunque esté compacta
        assert tabla.rowHeight(i) >= encabezado.sectionSizeFromContents(i).height()


def test_pagina_aprobada_no_muestra_pendientes(qtbot, importar, sin_dialogos, monkeypatch):
    monkeypatch.setattr(vista_importacion.QMessageBox, "information", lambda *_a, **_k: None)
    vista, _ = importar("tres.pdf", pdf_escaneado(TRES_CLASES))
    qtbot.addWidget(vista)
    assert vista.columna_pendientes.isVisible()  # grupos por validar (solo la letra)
    vista.aprobar({"aceptar_diferencia_horas": True})
    assert sin_dialogos == []
    assert vista.pagina["estado"] == "aprobada"
    assert not vista.columna_pendientes.isVisible()  # nada que revisar en una aprobada
    assert vista.boton_pendientes.text() == "Sin pendientes"


def test_agrandar_la_ventana_sigue_mostrando_el_horario(qtbot, importar):
    """Agrandar la ventana no cuenta como desplazamiento manual: se reajusta."""
    vista, _ = importar("tarde.pdf", pdf_escaneado(VESPERTINO), 620, 1100)
    qtbot.addWidget(vista)
    vista.resize(1440, 1000)
    _procesar()
    for hora in (17, 18, 19, 20):
        assert fila_visible_completa(vista.cuadricula, HORAS.index(hora)), hora
