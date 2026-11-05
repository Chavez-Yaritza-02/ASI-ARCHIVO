"""Nueva navegación de la interfaz contra la API real, con datos y PDF ficticios.

Comprueba que cada botón hace algo real: secciones por rol, atajos, Inicio, Reportes,
asistente de importación en cuatro pasos, cambio de periodo y componentes comunes.
"""

import io
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from horario_ficticio import UNO, pdf_escaneado
from openpyxl import load_workbook
from PySide6.QtGui import QShortcut

from app.main import app
from asi_cliente.api.cliente import ClienteApi, ErrorApi
from asi_cliente.views import asistente_importacion as vista_asistente
from asi_cliente.views import gestion_horarios as vista_gestion
from asi_cliente.views import inicio as vista_inicio
from asi_cliente.views import reportes as vista_reportes
from asi_cliente.views.asistencia_hora import VistaAsistenciaHora
from asi_cliente.views.asistente_importacion import VistaAsistenteImportacion
from asi_cliente.views.comunes import Columna, Tabla, explicar_error
from asi_cliente.views.configuracion import VistaConfiguracion
from asi_cliente.views.horarios import VistaHorarios
from asi_cliente.views.periodos import VistaPeriodos
from asi_cliente.views.reportes import VistaReportes
from asi_cliente.views.ventana_principal import VentanaPrincipal

os.environ["ASI_OCR_PROCESOS"] = "1"
CONTRASENA = "contrasena-de-prueba"  # igual que en conftest.py
LUNES = date(2026, 11, 2)


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
    api.post("/docentes", {"nombre": "DOCENTE PRUEBA DOS", "nomina": "ZZX0002"})
    api.post("/asignaturas", {"nombre": "CÁLC. DIF."})
    api.post("/asignaturas", {"nombre": "GESTIÓN ACADÉMICA", "tipo": "actividad"})
    for aula in ("M01", "Sala EM"):
        api.post("/aulas", {"clave": aula})
    api.post("/grupos", {"letra": "A", "periodo_id": p["id"], "carrera": "IEM", "semestre": 3})
    return api


@pytest.fixture
def mensajes(monkeypatch):
    """Sustituye los cuadros de diálogo: se confirma todo y se guardan los errores."""
    errores: list = []
    for modulo in (vista_asistente, vista_gestion, vista_reportes):
        if hasattr(modulo, "mostrar_error"):
            monkeypatch.setattr(modulo, "mostrar_error", lambda _p, e, *_a: errores.append(e))
        if hasattr(modulo, "confirmar"):
            monkeypatch.setattr(modulo, "confirmar", lambda *_a, **_k: True)
    return errores


def ids(api, ruta, campo, valor):
    return next(x["id"] for x in api.get(ruta) if x[campo] == valor)


def horario_vigente(api, docente, bloques):
    periodo = api.get("/periodos/activo")
    h = api.post(
        "/horarios",
        {"docente_id": ids(api, "/docentes", "nombre", docente), "periodo_id": periodo["id"]},
    )
    api.put(f"/horarios/{h['id']}/bloques", bloques)
    api.post(
        f"/horarios/{h['id']}/confirmar",
        {"aceptar_advertencias": True, "vigente_desde": "2026-08-17"},
    )
    return h["id"]


def ventana_de(qtbot, api) -> VentanaPrincipal:
    v = VentanaPrincipal(api.usuario, api)
    qtbot.addWidget(v)
    return v


# --- navegación y permisos ------------------------------------------------------------


def test_seis_secciones_con_sus_pantallas(qtbot, api):
    v = ventana_de(qtbot, api)
    assert [g[0] for g in v.grupos] == [
        "Inicio",
        "Asistencias",
        "Horarios",
        "Docentes",
        "Reportes",
        "Administración",
    ]
    horarios = v.abrir_grupo("Horarios")
    textos = [horarios.pestanas.tabText(i) for i in range(horarios.pestanas.count())]
    assert textos == ["Por docente", "Por grupo", "Importar horarios", "Registro de cambios"]
    assert v.titulo_seccion.text() == "Horarios"
    # Los nombres de siempre siguen abriendo la pantalla correcta (y una sola vez).
    assert isinstance(v.abrir_seccion("Horarios"), VistaHorarios)
    assert v.abrir_seccion("Gestión de horarios") is v.abrir_seccion("Horarios")
    assert isinstance(v.abrir_seccion("Importar horarios"), VistaAsistenteImportacion)
    assert isinstance(v.abrir_seccion("Periodos"), VistaPeriodos)
    assert v.titulo_seccion.text() == "Administración"
    assert isinstance(v.abrir_seccion("Configuración"), VistaConfiguracion)
    # El periodo activo se ve siempre en la barra superior.
    assert v.periodo.text() == "Periodo: AGOSTO - DICIEMBRE 2026"
    assert not v.boton_periodo.isHidden()


def test_consulta_solo_ve_y_no_modifica(qtbot, api, consulta):
    lector = api_de(consulta.correo)
    v = ventana_de(qtbot, lector)
    horarios = v.abrir_grupo("Horarios")
    assert "Importar horarios" not in horarios.nombres
    assert "Importar horarios" not in [s[0] for s in v.secciones]
    assert v.boton_periodo.isHidden()
    with pytest.raises(StopIteration):
        v.abrir_seccion("Importar horarios")
    inicio = v.abrir_seccion("Inicio")
    assert "Importar horarios" not in inicio.accesos
    assert "Asistencia por hora" not in inicio.accesos  # no registra asistencia
    assert v.abrir_seccion("Periodos").boton_nuevo.isHidden()
    assert v.periodo.text() == "Periodo: AGOSTO - DICIEMBRE 2026"


def test_atajos_de_teclado_y_menu_compacto(qtbot, api):
    v = ventana_de(qtbot, api)
    atajos = {s.key().toString(): s for s in v.findChildren(QShortcut)}
    assert set(atajos) >= {f"Ctrl+{i}" for i in range(1, 7)}
    atajos["Ctrl+3"].activated.emit()
    assert v.titulo_seccion.text() == "Horarios"
    atajos["Ctrl+6"].activated.emit()
    assert v.titulo_seccion.text() == "Administración"

    v.ajustar_menu(True)  # ventana angosta: solo iconos, el nombre queda en la ayuda
    assert v.lateral.width() == 76 and v.menu.item(0).text() == ""
    assert "Resumen del día" in v.menu.item(0).toolTip()
    v.ajustar_menu(False)
    assert v.menu.item(0).text() == "Inicio" and v.lateral.width() == 232


# --- Inicio y Reportes ----------------------------------------------------------------


def test_inicio_resume_el_dia_y_sus_accesos_navegan(qtbot, api, monkeypatch):
    class Hoy(date):
        @classmethod
        def today(cls):
            return LUNES

    monkeypatch.setattr(vista_inicio, "date", Hoy)
    calculo = ids(api, "/asignaturas", "nombre", "CÁLC. DIF.")
    m01 = ids(api, "/aulas", "clave", "M01")
    horario_vigente(
        api,
        "DOCENTE PRUEBA UNO",
        [
            {
                "dia": "lunes",
                "hora_inicio": "07:00",
                "hora_fin": "09:00",
                "asignatura_id": calculo,
                "grupo_letra": "A",
                "aula_id": m01,
            }
        ],
    )
    fila = api.get("/bitacora/horas", fecha=LUNES.isoformat())["filas"][0]
    api.post(
        "/asistencias/horas",
        {
            "docente_id": fila["docente_id"],
            "fecha": LUNES.isoformat(),
            "bloque_id": fila["bloque_id"],
            "programado_inicio": fila["programado_inicio"],
            "estado": "falto",
        },
    )
    v = ventana_de(qtbot, api)
    inicio = v.abrir_seccion("Inicio")
    assert inicio.cifras["programadas"].text() == "2"
    assert inicio.cifras["falto"].text() == "1"
    assert inicio.cifras["pendientes"].text() == "1"
    assert inicio.tabla.rowCount() == 2 and not inicio.tabla.vacio.isVisible()
    assert inicio.buscar.text() == ""
    inicio.buscar.setText("no-existe")
    assert all(inicio.tabla.isRowHidden(i) for i in range(2))
    inicio.buscar.clear()

    inicio.accesos["Asistencia por hora"].click()
    assert v.titulo_seccion.text() == "Asistencias"
    asistencias = v.abrir_grupo("Asistencias")
    assert isinstance(asistencias.pestanas.currentWidget(), VistaAsistenciaHora)
    v.abrir_seccion("Inicio").accesos["Reportes"].click()
    assert v.titulo_seccion.text() == "Reportes"


def test_reportes_generan_pdf_y_excel_reales(qtbot, api, mensajes, tmp_path):
    calculo = ids(api, "/asignaturas", "nombre", "CÁLC. DIF.")
    grupo = api.get("/grupos")[0]["id"]
    horario_vigente(
        api,
        "DOCENTE PRUEBA UNO",
        [
            {
                "dia": "lunes",
                "hora_inicio": "07:00",
                "hora_fin": "08:00",
                "asignatura_id": calculo,
                "grupo_id": grupo,
            }
        ],
    )
    v = ventana_de(qtbot, api)
    r = v.abrir_seccion("Reportes")
    assert isinstance(r, VistaReportes)
    r.fecha.setDate(LUNES)

    r.opciones["asistencia_dia"].setChecked(True)
    assert r.generar_a(tmp_path / "dia.pdf")
    assert (tmp_path / "dia.pdf").read_bytes().startswith(b"%PDF")
    assert not r.boton_abrir.isHidden() and "dia.pdf" in r.resultado.text()

    r.opciones["asistencia_rango"].setChecked(True)
    r.excel.setChecked(True)
    r.desde.setDate(date(2026, 11, 2))
    r.hasta.setDate(date(2026, 11, 6))
    assert r.generar_a(tmp_path / "rango.xlsx")
    assert load_workbook(io.BytesIO((tmp_path / "rango.xlsx").read_bytes())).sheetnames

    r.opciones["bitacora"].setChecked(True)
    assert not r.docente.isEnabled()  # la bitácora no filtra por docente
    assert r.generar_a(tmp_path / "bitacora.xlsx")

    r.opciones["grupo"].setChecked(True)
    r.pdf.setChecked(True)
    assert r.grupo.currentData() == grupo
    assert r.generar_a(tmp_path / "grupo.pdf")
    assert r.nombre_sugerido() == "horario_grupo_2026-11-02.pdf"

    # Rango al revés: mensaje claro y no se genera nada.
    r.opciones["asistencia_rango"].setChecked(True)
    r.desde.setDate(date(2026, 11, 6))
    r.hasta.setDate(date(2026, 11, 2))
    assert not r.generar_a(tmp_path / "mal.pdf")
    assert "anterior" in str(mensajes[-1]) and not (tmp_path / "mal.pdf").exists()


# --- Asistente de importación ---------------------------------------------------------


def test_asistente_de_importacion_en_cuatro_pasos(qtbot, api, mensajes, tmp_path):
    # Otro docente ya ocupa el aula M01 el lunes a las 7: debe verse como conflicto.
    gestion = ids(api, "/asignaturas", "nombre", "GESTIÓN ACADÉMICA")
    m01 = ids(api, "/aulas", "clave", "M01")
    horario_vigente(
        api,
        "DOCENTE PRUEBA DOS",
        [
            {
                "dia": "lunes",
                "hora_inicio": "07:00",
                "hora_fin": "08:00",
                "asignatura_id": gestion,
                "aula_id": m01,
            }
        ],
    )
    archivo = tmp_path / "horario_uno.pdf"
    archivo.write_bytes(pdf_escaneado(UNO))

    v = ventana_de(qtbot, api)
    a = v.abrir_seccion("Importar horarios")
    # Paso 1: periodo activo preseleccionado.
    assert a.pasos.currentIndex() == 0 and a.marcas[0].objectName() == "paso_actual"
    assert a.periodo.currentText().startswith("AGOSTO - DICIEMBRE 2026")
    assert a.boton_siguiente.isEnabled()
    a.siguiente()
    # Paso 2: sin archivo no se puede subir ni avanzar.
    assert a.pasos.currentIndex() == 1
    assert not a.boton_subir.isEnabled() and not a.boton_siguiente.isEnabled()
    a.usar_archivo(archivo)
    assert a.boton_subir.isEnabled()
    a.subir()
    assert a.importacion["estado"] == "en_revision" and "terminada" in a.estado_subida.text()
    a.siguiente()
    # Paso 3: la pantalla de revisión muestra la página leída por OCR.
    assert a.pasos.currentIndex() == 2 and a.revision.pagina is not None
    assert a.revision.periodo.isHidden() and a.revision.boton_importar.isHidden()
    pagina = a.revision.pagina
    # Corrección del OCR (las materias y aulas que faltaban se crean).
    nuevas = {}
    for c in pagina["celdas_detalle"]:
        if c["asignatura_id"] is None:
            tipo = "actividad" if c["grupo_letra"] is None else "materia"
            nuevas[c["actividad_texto"]] = api.post(
                "/asignaturas", {"nombre": c["actividad_texto"], "tipo": tipo}
            )["id"]
    aulas = {x["clave"]: x["id"] for x in api.get("/aulas")}
    for clave in ("M05", "DOM-03"):
        aulas.setdefault(clave, api.post("/aulas", {"clave": clave})["id"])
    celdas = [
        {
            "id": c["id"],
            "dia": c["dia"],
            "hora": c["hora"],
            "asignatura_id": c["asignatura_id"] or nuevas[c["actividad_texto"]],
            "aula_id": c["aula_id"] or aulas.get(c["aula_texto"]),
            "grupo_id": None,
            "grupo_letra": c["grupo_letra"],
            "confirmar": True,
        }
        for c in pagina["celdas_detalle"]
    ]
    api.put(f"/importaciones/paginas/{pagina['id']}", {"celdas": celdas})
    api.post(f"/importaciones/paginas/{pagina['id']}/aceptar-sugerencias")
    a.siguiente()
    # Paso 4: el conflicto con el otro docente se ve antes de confirmar.
    assert a.pasos.currentIndex() == 3 and a.boton_siguiente.isHidden()
    tipos = [a.tabla_resumen.item(i, 3).text() for i in range(a.tabla_resumen.rowCount())]
    assert "Conflicto" in tipos
    assert a.boton_aprobar.isEnabled() and not a.boton_confirmar.isEnabled()
    a.aprobar_listas()
    assert "Se crearon 1 borrador" in a.conteo.text() and a.boton_confirmar.isEnabled()
    a.vigente_desde.setDate(date(2026, 8, 17))
    a.confirmar_borradores()
    assert mensajes == []
    uno = ids(api, "/docentes", "nombre", "DOCENTE PRUEBA UNO")
    vigentes = api.get("/horarios", docente_id=uno, estado="vigente")
    assert len(vigentes) == 1
    detalle = api.get(f"/horarios/{vigentes[0]['id']}")
    assert (
        detalle["vigente_desde"] == "2026-08-17"
        and detalle["periodo"]["nombre"] == "AGOSTO - DICIEMBRE 2026"
    )
    # Reiniciar deja el asistente listo para otra importación.
    a.reiniciar()
    assert a.pasos.currentIndex() == 0 and a.importacion is None


def test_asistente_crea_un_periodo_nuevo(qtbot, api, mensajes, monkeypatch):
    class Formulario:
        def __init__(self, *_a, **_k):
            self.veces = 0

        def exec(self):
            self.veces += 1
            return self.veces == 1

        def valores(self):
            return {
                "nombre": "Enero - Junio 2027",
                "fecha_inicio": "2027-01-15",
                "fecha_fin": "2027-06-30",
            }

    monkeypatch.setattr(vista_asistente, "DialogoFormulario", Formulario)
    v = ventana_de(qtbot, api)
    a = v.abrir_seccion("Importar horarios")
    a.crear_periodo()
    assert a.periodo.currentText() == "ENERO - JUNIO 2027 (aún no activo)"
    assert "todavía no está activo" in a.detalle_periodo.text()
    # El periodo activo no cambia: los semestres quedan separados.
    assert api.get("/periodos/activo")["nombre"] == "AGOSTO - DICIEMBRE 2026"


# --- Periodo, configuración y componentes ---------------------------------------------


def test_cambiar_periodo_desde_la_barra_superior(qtbot, api, mensajes, monkeypatch):
    api.post(
        "/periodos",
        {"nombre": "Enero - Junio 2027", "fecha_inicio": "2027-01-15", "fecha_fin": "2027-06-30"},
    )
    monkeypatch.setattr(vista_gestion.DialogoCambiarPeriodo, "exec", lambda self: True)
    v = ventana_de(qtbot, api)
    v.cambiar_periodo()
    assert mensajes == []
    assert v.periodo.text() == "Periodo: ENERO - JUNIO 2027"
    estados = {p["nombre"]: p["estado"] for p in api.get("/periodos")}
    assert estados["AGOSTO - DICIEMBRE 2026"] == "cerrado"


def test_configuracion_tiene_funciones_reales(qtbot, api):
    v = ventana_de(qtbot, api)
    c = v.abrir_seccion("Configuración")
    assert c.probar_conexion() and c.estado_servidor.text() == "Conectado y funcionando"
    senales = []
    v.cambiar_tema.connect(lambda: senales.append("tema"))
    v.cerrar_sesion.connect(lambda: senales.append("salir"))
    c.boton_tema.click()
    c.boton_salir.click()
    assert senales == ["tema", "salir"]


def test_tabla_con_busqueda_y_estado_vacio(qtbot):
    t = Tabla([Columna("Nombre", lambda f: f["n"])], "Aún no hay docentes.")
    qtbot.addWidget(t)
    t.show()
    assert t.vacio.isVisible() and t.vacio.text() == "Aún no hay docentes."
    t.cargar([{"n": "Ana"}, {"n": "Beto"}, {"n": "Carla"}])
    assert not t.vacio.isVisible()
    assert t.filtrar("be") == 1 and t.isRowHidden(0) and not t.isRowHidden(1)
    assert t.filtrar("zzz") == 0 and t.vacio.isVisible() and "zzz" in t.vacio.text()
    t.cargar([{"n": "Beatriz"}, {"n": "Diego"}])  # el filtro se conserva al recargar
    assert t.vacio.isVisible()
    assert t.filtrar("") == 2 and not t.vacio.isVisible()


def test_errores_en_lenguaje_sencillo():
    assert explicar_error(ErrorApi("No se pudo conectar con el servidor"))[0] == (
        "No hay conexión con el servidor."
    )
    assert "permiso" in explicar_error(ErrorApi("Forbidden", [], 403))[0]
    assert "sesión terminó" in explicar_error(ErrorApi("x", [], 401))[0]
    assert "No se guardó nada" in explicar_error(ErrorApi("Internal", [], 500))[1]
    assert explicar_error(ErrorApi("Ya existe un periodo llamado X", [], 409)) == (
        "Ya existe un periodo llamado X",
        "",
    )
