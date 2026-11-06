"""Un PDF que se sube por segunda vez no debe dejar la revisión vacía y sin explicación.

Caso real reportado: el PDF de una docente ya venía dentro de un ZIP importado antes. Al
subirlo solo, el servidor lo marcaba como duplicado (correcto) pero la pantalla mostraba
la importación nueva sin páginas y sin decir dónde estaban sus clases.
Todos los datos son ficticios.
"""

import os
from dataclasses import replace

from horario_ficticio import DOS, UNO, pdf_escaneado, zip_con
from test_interfaz_navegacion import api, mensajes, ventana_de  # noqa: F401

from asi_cliente.views.importacion import VistaImportacion, importacion_original

os.environ["ASI_OCR_PROCESOS"] = "1"
# Mismos bytes en todas las subidas (el generador ficticio no es determinista).
PDF_UNO = pdf_escaneado(UNO)


def subir(api, nombre, contenido):  # noqa: F811
    periodo = api.get("/periodos/activo")["id"]
    lote = api.subir("/importaciones", nombre, contenido, {"periodo_id": str(periodo)})
    return api.get(f"/importaciones/{lote['id']}")


def test_api_indica_la_importacion_original(api):  # noqa: F811
    zip_ = zip_con({"uno.pdf": PDF_UNO, "dos.pdf": pdf_escaneado(DOS)})
    original = subir(api, "horarios.zip", zip_)
    repetido = subir(api, "UNO SOLO.pdf", PDF_UNO)
    doc = repetido["documentos"][0]
    assert doc["estado"] == "duplicado" and doc["paginas"] == []
    assert doc["original_importacion_id"] == original["id"]
    # Los documentos leídos no apuntan a ninguna otra importación.
    assert all(d["original_importacion_id"] is None for d in original["documentos"])
    # La importación original conserva intactas sus páginas y celdas.
    paginas = [p for d in original["documentos"] for p in d["paginas"]]
    assert len(paginas) == 2 and all(p["celdas"] > 0 for p in paginas)


def test_revision_explica_el_duplicado_y_abre_el_original(qtbot, api, mensajes):  # noqa: F811
    original = subir(api, "uno.pdf", PDF_UNO)
    repetido = subir(api, "copia de uno.pdf", PDF_UNO)
    vista = VistaImportacion(api, api.usuario)
    qtbot.addWidget(vista)
    vista.seleccionar_importacion(repetido["id"])

    assert vista.paginas.rowCount() == 0
    assert not vista.aviso_lote.isHidden()
    assert f"importación #{original['id']}" in vista.aviso_lote.text()
    assert not vista.boton_original.isHidden()

    vista.boton_original.click()
    assert vista.importacion["id"] == original["id"]
    assert vista.paginas.rowCount() == 1 and vista.pagina is not None
    assert len(vista.pagina["celdas_detalle"]) == 5  # las clases se ven en la vista previa
    assert vista.boton_original.isHidden()
    assert mensajes == []


def test_asistente_lleva_a_las_clases_de_un_pdf_ya_importado(
    qtbot,
    api,  # noqa: F811
    mensajes,  # noqa: F811
    tmp_path,
):
    original = subir(api, "uno.pdf", PDF_UNO)
    archivo = tmp_path / "uno otra vez.pdf"
    archivo.write_bytes(PDF_UNO)
    v = ventana_de(qtbot, api)
    a = v.abrir_seccion("Importar horarios")
    a.siguiente()
    a.usar_archivo(archivo)
    a.subir()
    assert a.importacion["id"] == original["id"]
    assert "ya se había importado" in a.estado_subida.text()
    a.siguiente()
    assert a.revision.pagina is not None
    assert len(a.revision.pagina["celdas_detalle"]) == 5
    assert mensajes == []


def test_pagina_sin_clases_reconocidas_se_puede_capturar_a_mano(qtbot, api, mensajes):  # noqa: F811
    lote = subir(api, "vacio.pdf", pdf_escaneado(replace(UNO, clases=[])))
    vista = VistaImportacion(api, api.usuario)
    qtbot.addWidget(vista)
    vista.seleccionar_importacion(lote["id"])
    assert vista.pagina is not None and vista.pagina["celdas_detalle"] == []
    assert "no reconoció ninguna clase" in vista.avisos.text()
    assert vista._editable()  # se puede revisar y capturar a mano
    assert vista.aviso_lote.isHidden()


def test_servidor_anterior_sin_el_campo_nuevo():
    """Con un servidor no actualizado, el número se toma del mensaje que ya enviaba."""
    viejo = {
        "estado": "duplicado",
        "mensaje": "Idéntico a VIDRIO MORA ELISA.pdf (importación 2)",
        "paginas": [],
    }
    assert importacion_original(viejo) == 2
    assert importacion_original({**viejo, "original_importacion_id": 5}) == 5
    assert importacion_original({"estado": "procesado", "mensaje": ""}) is None
    assert importacion_original({"estado": "duplicado", "mensaje": "otro texto"}) is None


def test_cuadricula_baja_hasta_clases_vespertinas(qtbot, api, mensajes):  # noqa: F811
    """Un horario de 17:00 en adelante no debe verse vacío al abrirlo."""
    from horario_ficticio import Clase

    from asi_cliente.cuadricula import HORAS, fila_visible_completa

    tarde = replace(UNO, clases=[Clase(0, 17, "CALC. DIF.", "A", "M01")])
    lote = subir(api, "tarde.pdf", pdf_escaneado(tarde))
    vista = VistaImportacion(api, api.usuario)
    qtbot.addWidget(vista)
    vista.resize(1200, 600)
    vista.show()
    vista.seleccionar_importacion(lote["id"])
    assert [c["hora"] for c in vista.pagina["celdas_detalle"]] == [17]
    # La clase de las 17:00 se ve completa (antes la tabla se quedaba en las 07:00).
    assert fila_visible_completa(vista.cuadricula, HORAS.index(17))
