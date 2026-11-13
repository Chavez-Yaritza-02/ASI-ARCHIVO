"""Ventanas de captura manual de horarios e importación de incidencias desde Excel.

Contra la API real (PostgreSQL o SQLite de pruebas) y solo con datos ficticios.
"""

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import Qt
from sqlalchemy import select

from app.main import app
from app.models import AsistenciaHora, BloqueHorario, Horario
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.cuadricula import Celda
from asi_cliente.views import horarios as vista_horarios
from asi_cliente.views import incidencias_excel as vista_incidencias
from asi_cliente.views.horarios import VistaHorarios
from asi_cliente.views.incidencias_excel import DialogoIncidencia, VistaIncidenciasExcel
from server.tests.test_incidencias_excel import ALFA, excel

pytest_plugins = ["server.tests.test_incidencias_excel"]


@pytest.fixture
def api(admin, escuela):
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(admin.correo, "contrasena-de-prueba")
    return api


@pytest.fixture
def avisos(monkeypatch):
    """Respuestas automáticas a las preguntas y registro de avisos y errores."""
    registro = {"confirmar": [], "informar": [], "errores": [], "respuesta": True}

    def confirmar(_padre, pregunta, *_a, **_k):
        registro["confirmar"].append(pregunta)
        return registro["respuesta"]

    for modulo in (vista_horarios, vista_incidencias):
        monkeypatch.setattr(modulo, "confirmar", confirmar)
        monkeypatch.setattr(
            modulo, "informar", lambda _p, titulo, *_a: registro["informar"].append(titulo)
        )
        monkeypatch.setattr(
            modulo, "mostrar_error", lambda _p, e, *_a: registro["errores"].append(str(e))
        )
    return registro


def ids(api, ruta):
    return {r.get("nombre") or r.get("clave"): r["id"] for r in api.get(ruta)}


def responder_clases(monkeypatch, clases):
    """Sustituye la ventana «Agregar clase» por respuestas preparadas."""
    pendientes = list(clases)

    class Dialogo:
        def __init__(self, *_a):
            self.actual = pendientes.pop(0) if pendientes else None

        def exec(self):
            return self.actual is not None

        def clase(self):
            actual, self.actual = self.actual, None
            return actual

    monkeypatch.setattr(vista_horarios, "DialogoClase", Dialogo)


def clase(api, dia, inicio, fin, materia="CÁLC. DIF.", grupo="IEM 3A", aula="M01"):
    grupos = {g["clave"]: g["id"] for g in api.get("/grupos")}
    celda = Celda(
        ids(api, "/asignaturas")[materia], grupos.get(grupo), ids(api, "/aulas").get(aula)
    )
    return {"dia": dia, "inicio": inicio, "fin": fin, "celda": celda}


def elegir_docente(v, nombre):
    v.docente.setCurrentIndex(v.docente.findText(nombre, Qt.MatchStartsWith))
    v.cargar_versiones()


def test_captura_manual_completa_con_duplicados_y_traslapes(
    qtbot, api, avisos, monkeypatch, sesion
):
    api.post("/asignaturas", {"nombre": "DINÁMICA"})
    v = VistaHorarios(api, api.usuario)
    qtbot.addWidget(v)

    # Profesor nuevo desde la misma pantalla.
    class Formulario:
        def __init__(self, *_a, **_k):
            self.pendiente = True

        def exec(self):
            pendiente, self.pendiente = self.pendiente, False
            return pendiente

        def valores(self):
            return {"nombre": "DOCENTE FICTICIO NUEVO", "nomina": None}

    monkeypatch.setattr(vista_horarios, "DialogoFormulario", Formulario)
    v.nuevo_docente()
    assert v._docente()["nombre"] == "DOCENTE FICTICIO NUEVO"
    assert v.horario is None

    responder_clases(
        monkeypatch,
        [
            clase(api, "lunes", 7, 9),
            clase(api, "lunes", 11, 12, aula="M01"),  # varias clases el mismo día
            clase(api, "martes", 10, 11),
            clase(api, "lunes", 7, 9),  # repetida: no se duplica
        ],
    )
    for _ in range(4):
        v.agregar_clase()
    assert avisos["informar"] == ["Esa clase ya está en el horario"]
    assert v.horario["estado"] == "borrador"  # se creó solo, sin horario previo
    assert [(c["dia"], c["inicio"], c["fin"]) for c in v._clases()] == [
        ("lunes", 7, 9),
        ("lunes", 11, 12),
        ("martes", 10, 11),
    ]
    # Traslape con otra clase del mismo horario: se pregunta y, si no, no cambia nada.
    avisos["respuesta"] = False
    responder_clases(monkeypatch, [clase(api, "lunes", 8, 10, materia="DINÁMICA")])
    v.agregar_clase()
    assert "Esas horas ya tienen otra clase" in avisos["confirmar"][-1]
    assert len(v._clases()) == 3
    avisos["respuesta"] = True
    assert v.guardar()

    # Se guardó en la base (otra sesión) y otra ventana lo ve igual.
    sesion.expire_all()
    guardado = sesion.get(Horario, v.horario["id"])
    assert len(guardado.bloques) == 3
    otra = VistaHorarios(api, api.usuario)
    qtbot.addWidget(otra)
    elegir_docente(otra, "DOCENTE FICTICIO NUEVO")
    assert len(otra._clases()) == 3 and otra.lista.rowCount() == 3

    # Confirmarla y luego corregir: se crea otra versión, la vigente no cambia.
    assert (
        api.post(
            f"/horarios/{v.horario['id']}/confirmar",
            {"vigente_desde": "2026-08-17", "aceptar_advertencias": True},
        )["estado"]
        == "vigente"
    )
    vigente_id = v.horario["id"]
    v.cargar_versiones()
    v.vistas.setCurrentWidget(v.lista)
    v.lista.selectRow(2)  # martes 10–11
    responder_clases(monkeypatch, [clase(api, "martes", 11, 13)])
    v.editar_clase()
    assert any("nueva versión" in p for p in avisos["confirmar"])
    assert v.horario["id"] != vigente_id and v.horario["estado"] == "borrador"
    assert ("martes", 11, 13) in [(c["dia"], c["inicio"], c["fin"]) for c in v._clases()]
    assert ("martes", 10, 11) not in [(c["dia"], c["inicio"], c["fin"]) for c in v._clases()]
    v.vistas.setCurrentWidget(v.cuadricula)
    v.cuadricula.setCurrentCell(11 - 7, 0)  # lunes 11:00
    v.eliminar_clase()
    assert [(c["dia"], c["inicio"]) for c in v._clases()] == [("lunes", 7), ("martes", 11)]
    assert v.guardar()
    sesion.expire_all()
    assert len(sesion.get(Horario, vigente_id).bloques) == 3  # la vigente intacta
    assert avisos["errores"] == []


def test_choque_con_otro_docente_se_avisa_al_guardar(qtbot, api, avisos, monkeypatch):
    v = VistaHorarios(api, api.usuario)
    qtbot.addWidget(v)
    elegir_docente(v, "DOCENTE FICTICIO BETA")
    # ALFA tiene el jueves 07–09 en M01 con el grupo IEM 3A.
    responder_clases(monkeypatch, [clase(api, "jueves", 7, 8)])
    v.agregar_clase()
    assert v.guardar()
    texto = v.advertencias.text()
    assert "Aula M01 ocupada" in texto and "Grupo" in texto and ALFA in texto


def test_semestre_nuevo_copia_clases_sin_tocar_el_anterior(qtbot, api, avisos, sesion):
    nuevo = api.post(
        "/periodos",
        {"nombre": "Enero - Junio 2027", "fecha_inicio": "2027-01-11", "fecha_fin": "2027-06-30"},
    )
    v = VistaHorarios(api, api.usuario)
    qtbot.addWidget(v)
    v.periodo.setCurrentIndex(v.periodo.findText("Enero - Junio 2027", Qt.MatchStartsWith))
    elegir_docente(v, ALFA)
    assert v.horario is None
    v.nueva_version()
    assert "AGOSTO - DICIEMBRE 2026" in avisos["confirmar"][-1]
    bloques = v.horario["bloques"]
    assert [(b["dia"], b["hora_inicio"], b["grupo"], b["grupo_letra"]) for b in bloques] == [
        ("jueves", "07:00:00", None, "A")  # el grupo del semestre nuevo queda por asignar
    ]
    assert v.horario["periodo"]["id"] == nuevo["id"]
    sesion.expire_all()
    anteriores = sesion.scalars(
        select(BloqueHorario).join(Horario).where(Horario.periodo_id != nuevo["id"])
    ).all()
    assert all(b.grupo_id is not None for b in anteriores)


# --- incidencias desde Excel ---------------------------------------------------------------


def test_vista_previa_revision_e_importacion_de_incidencias(qtbot, api, avisos, tmp_path, sesion):
    archivo = tmp_path / "incidencias-ficticias.xlsx"
    archivo.write_bytes(excel())
    v = VistaIncidenciasExcel(api, api.usuario)
    qtbot.addWidget(v)
    v.cargar_archivo(archivo)
    assert v.tabla.rowCount() == 5
    assert not v.boton_importar.isEnabled()  # nada está listo sin elegir horas
    assert all(not (v.tabla.item(n, 0).flags() & Qt.ItemIsUserCheckable) for n in range(5))

    # Caso especial: salida anticipada; solo la hora posterior a la salida.
    v.tabla.selectRow(0)
    d = DialogoIncidencia(api, v.tabla.seleccionado(), v.docentes, v)
    qtbot.addWidget(d)
    assert d.tipo.currentData() == "salida_anticipada"
    assert d.hora_salida.time().toString("HH:mm") == "19:00"
    assert d.horas.count() == 3
    assert d.horas_elegidas() == []  # nada se marca solo
    d.marcar_sugeridas()
    assert [h["programado_inicio"] for h in d.horas_elegidas()] == ["19:00:00"]
    d.observaciones.setText("Reporte ficticio de prefectura")
    d.guardar()
    assert d.result() == d.DialogCode.Accepted

    v.abrir(v.importacion["id"])
    assert v.importacion["listas"] == 1 and v.boton_importar.isEnabled()
    v.importar()  # sin marcar: no importa nada
    assert avisos["informar"][-1] == "Marca las filas confirmadas"
    v.marcar(v.tabla.filas[0]["id"])
    v.importar()
    assert avisos["informar"][-1] == "Incidencias importadas"
    assert [f["estado"] for f in v.tabla.filas] == ["importada"] + ["pendiente"] * 4
    sesion.expire_all()
    [registro] = sesion.scalars(select(AsistenciaHora)).all()
    assert registro.estado == "falto" and "Reporte ficticio de prefectura" in registro.observaciones

    # El mismo archivo otra vez: se abre la revisión existente, sin duplicar.
    v.cargar_archivo(archivo)
    assert avisos["informar"][-1] == "Este archivo ya se había cargado"
    assert len(api.get("/incidencias-excel")) == 1


def test_corregir_docente_no_encontrado_y_ver_sus_horas(qtbot, api, avisos, tmp_path):
    archivo = tmp_path / "incidencias-ficticias.xlsx"
    archivo.write_bytes(excel())
    v = VistaIncidenciasExcel(api, api.usuario)
    qtbot.addWidget(v)
    v.cargar_archivo(archivo)
    v.tabla.selectRow(4)  # DOCENTE INEXISTENTE ZETA, 07/10/2026 (miércoles)
    d = DialogoIncidencia(api, v.tabla.seleccionado(), v.docentes, v)
    qtbot.addWidget(d)
    assert d.docente.currentData() is None and "No se encontró" in d.estado_docente.text()
    d.docente.setCurrentIndex(d.docente.findText("DOCENTE FICTICIO BETA"))
    d.aplicar_y_ver_horas()
    assert d.fila["docente_estado"] == "confirmado"
    assert d.horas.count() == 1 and "07:00–08:00" in d.horas.item(0).text()
    d.horas.item(0).setCheckState(Qt.Checked)
    d.guardar()
    v.abrir(v.importacion["id"])
    assert v.tabla.filas[4]["lista"] is True
    assert avisos["errores"] == []


def test_archivo_que_no_es_excel_no_guarda_nada(qtbot, api, avisos, tmp_path):
    archivo = tmp_path / "no-es-excel.xlsx"
    archivo.write_bytes(b"texto ficticio")
    v = VistaIncidenciasExcel(api, api.usuario)
    qtbot.addWidget(v)
    v.cargar_archivo(archivo)
    assert avisos["errores"] and "no es un Excel" in avisos["errores"][0]
    assert api.get("/incidencias-excel") == [] and v.tabla.rowCount() == 0


def test_ventana_agregar_clase_valida_horas_y_grupo(qtbot, api):
    catalogos = {k: api.get(f"/{k}") for k in ("asignaturas", "grupos", "aulas")}
    d = vista_horarios.DialogoClase(catalogos)
    qtbot.addWidget(d)
    d.dia.setCurrentIndex(d.dia.findData("viernes"))
    d.inicio.setCurrentIndex(d.inicio.findData(17))
    assert d.fin.currentData() == 18  # el fin se ajusta para quedar después del inicio
    d.fin.setCurrentIndex(d.fin.findData(20))
    d.asignatura.setCurrentIndex(d.asignatura.findText("CÁLC. DIF."))
    assert d.problema() == "Una materia necesita grupo."
    d._aceptar()
    assert d.result() != d.DialogCode.Accepted and "grupo" in d.mensaje.text()
    d.grupo.setCurrentIndex(d.grupo.findText("IEM 3A"))
    d.aula.setCurrentIndex(d.aula.findText("M01"))
    d.inicio.setCurrentIndex(d.inicio.findData(19))
    d.fin.setCurrentIndex(d.fin.findData(19))
    assert "posterior" in d.problema()
    d.fin.setCurrentIndex(d.fin.findData(21))
    assert d.problema() == ""
    elegida = d.clase()
    assert (elegida["dia"], elegida["inicio"], elegida["fin"]) == ("viernes", 19, 21)
    assert elegida["celda"].grupo_id is not None and elegida["celda"].aula_id is not None


def test_la_pantalla_aparece_en_asistencias(qtbot, api):
    from asi_cliente.views.ventana_principal import GRUPOS, secciones_visibles

    pestanas = dict(next(g[3] for g in GRUPOS if g[0] == "Asistencias"))
    assert pestanas["Importar incidencias"] == "Importar incidencias (Excel)"
    assert "Importar incidencias" in [s[0] for s in secciones_visibles(api.usuario)]
