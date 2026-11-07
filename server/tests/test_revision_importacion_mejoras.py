"""Paso 3 «Revisar» de Importar horarios: correcciones repetidas, sugerencias tolerantes,
desplazamiento a la primera clase y pendientes agrupados.

Todos los horarios, docentes, materias y aulas son ficticios.
"""

import os
from dataclasses import replace

import pytest
from horario_ficticio import DOS, UNO, Clase, pdf_escaneado
from PySide6.QtWidgets import QApplication
from test_interfaz_navegacion import api  # noqa: F401

from app.importers.coincidencias import (
    COINCIDE,
    SIN_COINCIDENCIA,
    SUGERIDO,
    buscar_asignatura,
    buscar_aula,
)
from asi_cliente.cuadricula import DIAS, HORAS, fila_visible_completa
from asi_cliente.views import importacion as vista_importacion
from asi_cliente.views.importacion import (
    COLORES,
    DialogoCeldaImportada,
    VistaImportacion,
    estado_celda,
)

os.environ["ASI_OCR_PROCESOS"] = "1"

# Tres celdas con la misma lectura («QUIM. ORG.») y una con un error de OCR («ELFCT»).
DOCUMENTO = replace(
    UNO,
    clases=[
        Clase(0, 7, "QUIM. ORG.", "A", "M01"),
        Clase(1, 7, "QUIM. ORG.", "A", "M01"),
        Clase(2, 7, "QUIM. ORG.", "B", "Sala EM"),
        Clase(3, 8, "SUB. ELFCT.", "A", "M01"),
    ],
)
# Otra docente en el mismo PDF, con la misma lectura: no debe tocarse.
OTRA = replace(DOS, clases=[Clase(0, 9, "QUIM. ORG.", "A", "M01")])


def subir(api, nombre, contenido):  # noqa: F811
    periodo = api.get("/periodos/activo")["id"]
    lote = api.subir("/importaciones", nombre, contenido, {"periodo_id": str(periodo)})
    return api.get(f"/importaciones/{lote['id']}")


def paginas(lote):
    return [p for d in lote["documentos"] for p in d["paginas"]]


def vista_de(qtbot, api, lote, pagina=None):  # noqa: F811
    vista = VistaImportacion(api, api.usuario)
    qtbot.addWidget(vista)
    vista.seleccionar_importacion(lote["id"])
    if pagina is not None:
        vista._cargar_pagina(pagina)
    return vista


def texto(vista, dia, hora) -> str:
    item = vista.cuadricula.item(HORAS.index(hora), DIAS.index(dia))
    return item.text() if item else ""


class DialogoQueElige:
    """Sustituye al diálogo: el usuario elige `valores` y pulsa «Aplicar»."""

    valores: dict = {}

    def __init__(self, _api, _catalogos, celda, *_a):
        self.celda = {**celda, **self.valores, "confirmar": True}
        self.celda["asignatura_estado"] = self.celda["aula_estado"] = "confirmado"

    def exec(self):
        return 1


@pytest.fixture
def dialogo(monkeypatch):
    monkeypatch.setattr(vista_importacion, "DialogoCeldaImportada", DialogoQueElige)
    DialogoQueElige.ELIMINAR = DialogoCeldaImportada.ELIMINAR
    return DialogoQueElige


@pytest.fixture
def pregunta(monkeypatch):
    """Registra la pregunta de corrección repetida y responde lo indicado en `respuesta`."""
    estado = {"respuesta": "todas", "llamadas": []}

    def falsa(_padre, cantidad, detalle):
        estado["llamadas"].append((cantidad, detalle))
        return estado["respuesta"]

    monkeypatch.setattr(vista_importacion, "preguntar_correccion_repetida", falsa)
    return estado


# --- 2. Comparación tolerante (sin base de datos) ----------------------------------------

CATALOGO = [
    (1, "SUB. ELECT."),
    (2, "Propiedades de los Materiales"),
    (3, "MEC. DE MATER"),
    (4, "MEC. DE MATERIA"),
    (5, "Manufactura Avan I"),
    (6, "Manufactura Avan II"),
    (7, "Administración de Mantenimiento"),
    (8, "TERMO"),
    (9, "TORNO"),
    (10, "ELECTRONICA"),
    (11, "ELECTRICIDAD"),
    (12, "QUÍMICA"),
]


@pytest.mark.parametrize(
    ("leido", "esperado"),
    [
        ("SUB. ELFCT.", 1),  # una letra mal leída (E/F)
        ("SUB.  ELFCT", 1),  # además, espacios y puntos distintos
        ("PROP. MAT.", 2),  # abreviatura habitual
        ("ADMON. DE MTTO.", 7),  # abreviaturas que no son el inicio de la palabra
        ("QUlMlCA", 12),  # l por I
        ("TFRMO", 8),  # texto corto: a lo más una letra
        ("Manufactura Avan Il", 6),  # «Il» es el numeral II
    ],
)
def test_coincidencia_aproximada_se_sugiere(leido, esperado):
    r = buscar_asignatura(leido, CATALOGO)
    assert (r.id, r.estado) == (esperado, SUGERIDO)


def test_mayusculas_espacios_y_signos_coinciden_exactamente():
    assert buscar_asignatura("sub elect", CATALOGO).estado == COINCIDE
    assert buscar_asignatura("SUB.ELECT", CATALOGO).estado == COINCIDE


@pytest.mark.parametrize(
    "leido",
    [
        "MEC. DE MATERI",  # a una letra de dos materias distintas
        "ELECT.",  # abreviatura de ELECTRONICA y de ELECTRICIDAD
        "Manufactura Avan",  # sin numeral no se sabe si es I o II
        "TOR",  # demasiado corto
        "XYZ",
    ],
)
def test_coincidencias_ambiguas_o_lejanas_no_se_proponen(leido):
    r = buscar_asignatura(leido, CATALOGO)
    assert r.id is None and r.estado == SIN_COINCIDENCIA


def test_materias_y_aulas_distintas_no_se_confunden():
    assert buscar_asignatura("TERMO", CATALOGO).id == 8
    assert buscar_asignatura("TORNO", CATALOGO).id == 9
    assert buscar_asignatura("MEC. DE MATER", CATALOGO).id == 3
    assert buscar_asignatura("MEC. DE MATERIA", CATALOGO).id == 4
    # Aulas: una sustitución (M01 / M02) nunca se toma por la otra.
    assert buscar_aula("M02", [(1, "M01")]).estado == SIN_COINCIDENCIA


def test_sugerencias_con_catalogo_nuevo_en_amarillo_y_con_aceptacion(qtbot, api, dialogo, pregunta):  # noqa: F811
    lote = subir(api, "sugerencias.pdf", pdf_escaneado(DOCUMENTO))
    pagina_id = paginas(lote)[0]["id"]
    # Las materias se dan de alta DESPUÉS de importar (el caso de la demostración).
    sub = api.post("/asignaturas", {"nombre": "SUB. ELECT."})
    api.post("/asignaturas", {"nombre": "QUÍMICA ORGÁNICA"})
    api.post("/asignaturas", {"nombre": "QUÍMICA ORGANOMETÁLICA"})

    antes = api.get(f"/importaciones/paginas/{pagina_id}")
    propuestas = api.get(f"/importaciones/paginas/{pagina_id}/sugerencias")
    assert api.get(f"/importaciones/paginas/{pagina_id}") == antes  # solo lectura
    por_campo = {(p["celda_id"], p["campo"]): p for p in propuestas["celdas"]}
    jueves = next(c for c in antes["celdas_detalle"] if c["dia"] == "jueves")
    assert por_campo[(jueves["id"], "asignatura")]["id"] == sub["id"]
    quimica = next(c for c in antes["celdas_detalle"] if c["dia"] == "lunes")
    ambigua = por_campo[(quimica["id"], "asignatura")]
    assert ambigua["id"] is None and len(ambigua["candidatos"]) == 2  # no se elige sola

    vista = vista_de(qtbot, api, lote)
    celda = vista.celdas[("jueves", 8)]
    assert estado_celda(celda) == "sugerido"
    item = vista.cuadricula.item(HORAS.index(8), DIAS.index("jueves"))
    assert item.background().color().name() == COLORES["sugerido"]  # amarillo
    assert "¿SUB. ELECT.?" in texto(vista, "jueves", 8)
    assert estado_celda(vista.celdas[("lunes", 7)]) == "falta"  # ambigua: sigue en rojo

    # Guardar sin aceptar no asigna nada.
    vista.cambios_pendientes = True
    assert vista.guardar()
    guardada = api.get(f"/importaciones/paginas/{pagina_id}")
    assert (
        next(c for c in guardada["celdas_detalle"] if c["id"] == jueves["id"])["asignatura_id"]
        is None
    )

    # «Aceptar coincidencias exactas» no la toma: es aproximada.
    assert not vista.boton_sugerencias.isEnabled()
    vista.aceptar_sugerencias()
    sigue = api.get(f"/importaciones/paginas/{pagina_id}")
    assert (
        next(c for c in sigue["celdas_detalle"] if c["id"] == jueves["id"])["asignatura_id"] is None
    )
    assert estado_celda(vista.celdas[("jueves", 8)]) == "sugerido"

    # Se confirma individualmente: doble clic → Aplicar (con la sugerencia preseleccionada).
    dialogo.valores = {"asignatura_id": sub["id"]}
    vista.editar_celda(HORAS.index(8), DIAS.index("jueves"))
    assert vista.guardar()
    aceptada = api.get(f"/importaciones/paginas/{pagina_id}")
    c = next(c for c in aceptada["celdas_detalle"] if c["id"] == jueves["id"])
    assert (c["asignatura_id"], c["asignatura_estado"]) == (sub["id"], "confirmado")


def test_sugerencia_al_importar_queda_como_sugerida(api):  # noqa: F811
    api.post("/asignaturas", {"nombre": "SUB. ELECT."})
    lote = subir(api, "al_importar.pdf", pdf_escaneado(DOCUMENTO))
    pagina = api.get(f"/importaciones/paginas/{paginas(lote)[0]['id']}")
    jueves = next(c for c in pagina["celdas_detalle"] if c["dia"] == "jueves")
    assert jueves["asignatura_estado"] == "sugerido"
    assert any("confirma la asignatura sugerida" in p for p in pagina["lista_pendientes"])


# --- 1. Correcciones repetidas -------------------------------------------------------------


def _quimica(api, vista):  # noqa: F811
    nueva = api.post("/asignaturas", {"nombre": "QUÍMICA ORGÁNICA"})
    vista.catalogos["asignaturas"].append(nueva)
    return nueva


def _asignaturas(vista):
    return {pos: c["asignatura_id"] for pos, c in vista.celdas.items()}


def test_correccion_repetida_todas_solo_en_esta_pagina(qtbot, api, dialogo, pregunta):  # noqa: F811
    lote = subir(api, "repetidas.pdf", pdf_escaneado(DOCUMENTO, OTRA))
    primera, segunda = paginas(lote)
    vista = vista_de(qtbot, api, lote, primera["id"])
    quimica = _quimica(api, vista)
    dialogo.valores = {"asignatura_id": quimica["id"]}

    vista.editar_celda(HORAS.index(7), DIAS.index("lunes"))
    cantidad, detalle = pregunta["llamadas"][0]
    assert cantidad == 2  # las otras dos celdas «QUIM. ORG.» de esta página
    assert "«QUIM. ORG.» → QUÍMICA ORGÁNICA" in detalle
    asignadas = _asignaturas(vista)
    assert [asignadas[(d, 7)] for d in ("lunes", "martes", "miercoles")] == [quimica["id"]] * 3
    assert asignadas[("jueves", 8)] is None  # otro texto: no se toca

    assert vista.guardar()
    guardada = api.get(f"/importaciones/paginas/{primera['id']}")
    quim = [c for c in guardada["celdas_detalle"] if c["actividad_texto"] == "QUIM. ORG."]
    assert {(c["asignatura_id"], c["asignatura_estado"]) for c in quim} == {
        (quimica["id"], "confirmado")
    }
    # Otra docente (otra página) con la misma lectura: intacta.
    otra = api.get(f"/importaciones/paginas/{segunda['id']}")
    assert [c["asignatura_id"] for c in otra["celdas_detalle"]] == [None]


def test_correccion_repetida_solo_esta_cancelar_y_deshacer(qtbot, api, dialogo, pregunta):  # noqa: F811
    lote = subir(api, "una.pdf", pdf_escaneado(DOCUMENTO))
    vista = vista_de(qtbot, api, lote)
    quimica = _quimica(api, vista)
    dialogo.valores = {"asignatura_id": quimica["id"]}
    original = _asignaturas(vista)

    # Cancelar: no cambia nada.
    pregunta["respuesta"] = None
    vista.editar_celda(HORAS.index(7), DIAS.index("lunes"))
    assert _asignaturas(vista) == original
    assert not vista.cambios_pendientes and not vista.boton_deshacer.isEnabled()

    # Solo esta celda.
    pregunta["respuesta"] = "una"
    vista.editar_celda(HORAS.index(7), DIAS.index("lunes"))
    asignadas = _asignaturas(vista)
    assert asignadas[("lunes", 7)] == quimica["id"]
    assert asignadas[("martes", 7)] is None and asignadas[("miercoles", 7)] is None

    # Todas (desde otra celda) y después deshacer paso a paso, antes de guardar.
    pregunta["respuesta"] = "todas"
    vista.editar_celda(HORAS.index(7), DIAS.index("martes"))
    assert pregunta["llamadas"][-1][0] == 1  # solo falta miércoles
    assert _asignaturas(vista)[("miercoles", 7)] == quimica["id"]
    assert vista.boton_deshacer.isEnabled()
    vista.boton_deshacer.click()
    assert _asignaturas(vista)[("miercoles", 7)] is None
    assert _asignaturas(vista)[("lunes", 7)] == quimica["id"]
    vista.deshacer()
    assert _asignaturas(vista) == original
    assert not vista.cambios_pendientes and not vista.boton_guardar.isEnabled()


def test_correccion_de_aula_y_grupo_repetidos(qtbot, api, dialogo, pregunta):  # noqa: F811
    lote = subir(api, "aulas.pdf", pdf_escaneado(DOCUMENTO))
    vista = vista_de(qtbot, api, lote)
    sala = next(a for a in vista.catalogos["aulas"] if a["clave"].upper() == "SALA EM")
    # Lunes y martes leen el aula «M01»: se cambia a Sala EM y la letra A por «C».
    dialogo.valores = {"aula_id": sala["id"], "grupo_id": None, "grupo_letra": "C"}
    vista.editar_celda(HORAS.index(7), DIAS.index("lunes"))
    cantidad, detalle = pregunta["llamadas"][0]
    assert cantidad == 2  # martes 7 (aula y grupo) y jueves 8 (aula y grupo)
    assert "Aula «M01» → " + sala["clave"] in detalle and "Grupo «A» → letra C" in detalle
    for pos in (("martes", 7), ("jueves", 8)):
        assert vista.celdas[pos]["aula_id"] == sala["id"]
        assert vista.celdas[pos]["grupo_letra"] == "C"
    assert vista.celdas[("miercoles", 7)]["grupo_letra"] == "B"  # otra letra: no se toca


# --- 3. Desplazamiento a la primera clase ------------------------------------------------


def _horario(docente, nomina, hora):
    return replace(
        UNO,
        docente=docente,
        nomina=nomina,
        clases=[
            Clase(0, hora, "CALC. DIF.", "A", "M01"),
            Clase(2, hora + 1, "CALC. DIF.", "A", "M01"),
        ],
    )


@pytest.fixture
def turnos(api):  # noqa: F811
    lote = subir(
        api,
        "turnos.pdf",
        pdf_escaneado(
            _horario("DOCENTE MATUTINO FICTICIO", "ZZX0101", 7),
            _horario("DOCENTE MEDIODIA FICTICIO", "ZZX0102", 13),
            _horario("DOCENTE VESPERTINO FICTICIO", "ZZX0103", 20),
        ),
    )
    return lote, {7: paginas(lote)[0]["id"], 13: paginas(lote)[1]["id"], 20: paginas(lote)[2]["id"]}


def _procesar():
    for _ in range(3):
        QApplication.processEvents()


@pytest.mark.parametrize("alto", [420, 640, 960])
def test_primera_clase_completa_en_varios_tamanos(qtbot, api, turnos, alto):  # noqa: F811
    lote, por_hora = turnos
    vista = vista_de(qtbot, api, lote)
    vista.resize(1280, alto)
    vista.show()
    qtbot.waitExposed(vista)
    for hora, pagina in por_hora.items():
        vista._cargar_pagina(pagina)
        _procesar()
        fila = HORAS.index(hora)
        assert fila_visible_completa(vista.cuadricula, fila), (hora, alto)
        if hora == 7:
            assert vista.cuadricula.verticalScrollBar().value() == 0


def test_desplazamiento_al_mostrar_y_redimensionar(qtbot, api, turnos):  # noqa: F811
    lote, por_hora = turnos
    vista = vista_de(qtbot, api, lote, por_hora[20])  # se carga aún oculta (asistente)
    vista.resize(1100, 500)
    vista.show()
    qtbot.waitExposed(vista)
    _procesar()
    fila = HORAS.index(20)
    assert fila_visible_completa(vista.cuadricula, fila)
    vista.resize(1100, 820)
    _procesar()
    assert fila_visible_completa(vista.cuadricula, fila)
    # Si el usuario desplaza a mano, ya no se le mueve la tabla.
    barra = vista.cuadricula.verticalScrollBar()
    barra.triggerAction(barra.SliderAction.SliderToMinimum)  # como la rueda o el arrastre
    vista.resize(1100, 600)
    _procesar()
    assert vista.cuadricula.verticalScrollBar().value() == 0


# --- 4. Pendientes agrupados ---------------------------------------------------------------


def test_pendientes_agrupados_localizan_la_celda(qtbot, api, dialogo):  # noqa: F811
    documento = replace(
        UNO,
        docente="DOCENTE NUEVA FICTICIA",
        nomina="ZZX0999",
        clases=[
            Clase(0, 7, "QUIM. ORG.", "A", "M01"),
            Clase(1, 8, "QUIM. ORG.", "A", "Z99"),
            Clase(2, 9, "CALC. DIF.", None, "M01"),
        ],
    )
    lote = subir(api, "pendientes.pdf", pdf_escaneado(documento))
    vista = vista_de(qtbot, api, lote)
    vista.resize(1400, 800)
    vista.show()
    qtbot.waitExposed(vista)

    arbol = vista.arbol_pendientes
    grupos = {
        arbol.topLevelItem(i).text(0): arbol.topLevelItem(i)
        for i in range(arbol.topLevelItemCount())
    }
    assert list(grupos) == ["Asignaturas (2)", "Grupos (1)", "Aulas (1)", "Docente (1)"]
    resumen = vista.lista_pendientes.text().replace("\u00a0", " ")
    assert "Falta revisar: 5" in resumen
    assert "Asignaturas 2 · Grupos 1 · Aulas 1 · Docente 1" in resumen
    assert "SIN GRUPO" in grupos["Grupos (1)"].child(0).text(0)

    # «SIN COINCIDENCIA» se ve completo: la columna mide al menos lo que el texto.
    metricas = arbol.fontMetrics()
    for grupo in grupos.values():
        for i in range(grupo.childCount()):
            hijo = grupo.child(i)
            if "SIN COINCIDENCIA" in hijo.text(0):
                ancho = max(metricas.horizontalAdvance(x) for x in hijo.text(0).split("\n"))
                assert arbol.columnWidth(0) >= arbol.indentation() + ancho
    assert "SIN COINCIDENCIA" in vista.estado_docente.text()
    assert vista.estado_docente.wordWrap()

    # Elegir un pendiente señala su celda en la cuadrícula.
    aula = grupos["Aulas (1)"].child(0)
    arbol.setCurrentItem(aula)
    assert (vista.cuadricula.currentRow(), vista.cuadricula.currentColumn()) == (
        HORAS.index(8),
        DIAS.index("martes"),
    )
    # Doble clic: abre la revisión de esa celda; al corregirla desaparece de la lista.
    m01 = next(a for a in vista.catalogos["aulas"] if a["clave"] == "M01")
    dialogo.valores = {"aula_id": m01["id"]}
    vista._editar_pendiente(aula)
    textos = [arbol.topLevelItem(i).text(0) for i in range(arbol.topLevelItemCount())]
    assert "Aulas (1)" not in textos
    assert "Aulas\u00a00" in vista.lista_pendientes.text()


# --- «Aceptar coincidencias exactas» -------------------------------------------------------

MEZCLA = replace(
    UNO,
    clases=[
        Clase(0, 7, "TALL. INV.", "A", "LAB 3"),  # exacta (se da de alta después)
        Clase(1, 7, "SUB. ELFCT.", "A", "M01"),  # aproximada (catálogo actual)
        Clase(2, 7, "FIS. GRAL", "A", "LAB 3"),  # aproximada al importar; aula exacta
    ],
)


def _celda(api, pagina_id, dia):  # noqa: F811
    detalle = api.get(f"/importaciones/paginas/{pagina_id}")
    return next(c for c in detalle["celdas_detalle"] if c["dia"] == dia)


def test_aceptar_exactas_deja_las_aproximadas_en_amarillo(qtbot, api, dialogo, pregunta):  # noqa: F811
    fisica = api.post("/asignaturas", {"nombre": "Física General"})  # antes: queda «sugerido»
    lote = subir(api, "mezcla.pdf", pdf_escaneado(MEZCLA))
    pagina_id = paginas(lote)[0]["id"]
    taller = api.post("/asignaturas", {"nombre": "TALL. INV."})
    sub = api.post("/asignaturas", {"nombre": "SUB. ELECT."})
    lab = api.post("/aulas", {"clave": "LAB 3"})
    assert _celda(api, pagina_id, "miercoles")["asignatura_estado"] == "sugerido"

    vista = vista_de(qtbot, api, lote)
    assert estado_celda(vista.celdas[("lunes", 7)]) == "exacta"
    item = vista.cuadricula.item(HORAS.index(7), DIAS.index("lunes"))
    assert item.background().color().name() == COLORES["exacta"]
    assert "TALL. INV." in texto(vista, "lunes", 7) and "¿" not in texto(vista, "lunes", 7)
    assert estado_celda(vista.celdas[("martes", 7)]) == "sugerido"
    assert estado_celda(vista.celdas[("miercoles", 7)]) == "sugerido"
    assert vista.boton_sugerencias.text() == "Aceptar coincidencias exactas"
    assert vista.boton_sugerencias.isEnabled()

    vista.boton_sugerencias.click()
    lunes, martes, miercoles = (_celda(api, pagina_id, d) for d in ("lunes", "martes", "miercoles"))
    # Exactas: aceptadas y confirmadas.
    assert (lunes["asignatura_id"], lunes["asignatura_estado"]) == (taller["id"], "confirmado")
    assert (lunes["aula_id"], lunes["aula_estado"]) == (lab["id"], "confirmado")
    assert (miercoles["aula_id"], miercoles["aula_estado"]) == (lab["id"], "confirmado")
    # Aproximadas: sin tocar, siguen en amarillo.
    assert martes["asignatura_id"] is None
    assert (miercoles["asignatura_id"], miercoles["asignatura_estado"]) == (
        fisica["id"],
        "sugerido",
    )
    assert estado_celda(vista.celdas[("martes", 7)]) == "sugerido"
    assert estado_celda(vista.celdas[("miercoles", 7)]) == "sugerido"
    assert not vista.boton_sugerencias.isEnabled()  # ya no quedan exactas
    hijos = [
        vista.arbol_pendientes.topLevelItem(0).child(i).text(0)
        for i in range(vista.arbol_pendientes.topLevelItem(0).childCount())
    ]
    assert len(hijos) == 2 and all("PARECIDA" in h for h in hijos)

    # Cada aproximada se confirma por separado.
    dialogo.valores = {"asignatura_id": sub["id"]}
    vista.editar_celda(HORAS.index(7), DIAS.index("martes"))
    assert vista.guardar()
    assert estado_celda(vista.celdas[("miercoles", 7)]) == "sugerido"  # la otra sigue igual
    dialogo.valores = {}  # Aplicar sin cambiar: confirma la sugerida
    vista.editar_celda(HORAS.index(7), DIAS.index("miercoles"))
    assert vista.guardar()
    assert _celda(api, pagina_id, "martes")["asignatura_estado"] == "confirmado"
    assert _celda(api, pagina_id, "miercoles")["asignatura_estado"] == "confirmado"


def test_docente_aproximado_se_confirma_aparte(qtbot, api):  # noqa: F811
    documento = replace(UNO, docente="DOCENTE PRUEBA UN0", nomina="ZZX9999")
    lote = subir(api, "docente_parecido.pdf", pdf_escaneado(documento))
    pagina_id = paginas(lote)[0]["id"]
    assert api.get(f"/importaciones/paginas/{pagina_id}")["docente_estado"] == "sugerido"

    vista = vista_de(qtbot, api, lote)
    assert not vista.boton_confirmar_docente.isHidden()
    vista.aceptar_sugerencias()  # no acepta docentes parecidos
    assert api.get(f"/importaciones/paginas/{pagina_id}")["docente_estado"] == "sugerido"

    vista.boton_confirmar_docente.click()
    assert vista.boton_confirmar_docente.isHidden()
    vista.deshacer()  # se puede deshacer antes de guardar
    assert not vista.boton_confirmar_docente.isHidden() and not vista.cambios_pendientes
    vista.boton_confirmar_docente.click()
    assert vista.guardar()
    assert api.get(f"/importaciones/paginas/{pagina_id}")["docente_estado"] == "confirmado"


def test_docente_exacto_dado_de_alta_despues_se_acepta(qtbot, api):  # noqa: F811
    documento = replace(UNO, docente="DOCENTE NUEVA EXACTA", nomina="ZZX0555")
    lote = subir(api, "docente_exacto.pdf", pdf_escaneado(documento))
    pagina_id = paginas(lote)[0]["id"]
    nueva = api.post("/docentes", {"nombre": "DOCENTE NUEVA EXACTA", "nomina": "ZZX0555"})
    vista = vista_de(qtbot, api, lote)
    vista.catalogos["docentes"].append(nueva)
    vista.docente.addItem(nueva["nombre"], nueva["id"])
    assert vista.boton_sugerencias.isEnabled()
    vista.boton_sugerencias.click()
    detalle = api.get(f"/importaciones/paginas/{pagina_id}")
    assert (detalle["docente"]["id"], detalle["docente_estado"]) == (nueva["id"], "confirmado")


def test_servidor_no_acepta_aproximadas_de_golpe(api):  # noqa: F811
    """Aunque una versión anterior de la aplicación lo pida, el servidor solo acepta exactas."""
    fisica = api.post("/asignaturas", {"nombre": "Física General"})  # aproximada al importar
    lote = subir(api, "servidor.pdf", pdf_escaneado(MEZCLA))
    pagina_id = paginas(lote)[0]["id"]
    taller = api.post("/asignaturas", {"nombre": "TALL. INV."})  # exacta, alta posterior
    api.post("/asignaturas", {"nombre": "SUB. ELECT."})  # aproximada, alta posterior

    api.post(f"/importaciones/paginas/{pagina_id}/aceptar-sugerencias")
    lunes, martes, miercoles = (_celda(api, pagina_id, d) for d in ("lunes", "martes", "miercoles"))
    assert (lunes["asignatura_id"], lunes["asignatura_estado"]) == (taller["id"], "confirmado")
    assert martes["asignatura_id"] is None  # «SUB. ELFCT.»: no se asigna sola
    assert (miercoles["asignatura_id"], miercoles["asignatura_estado"]) == (
        fisica["id"],
        "sugerido",  # sigue esperando confirmación individual
    )
    pendientes = api.get(f"/importaciones/paginas/{pagina_id}")["lista_pendientes"]
    assert any("confirma la asignatura sugerida" in p for p in pendientes)
