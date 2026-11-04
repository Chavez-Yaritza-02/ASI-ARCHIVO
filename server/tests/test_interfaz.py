"""Pruebas de la interfaz gráfica contra la API real y la base de datos de pruebas.

El cliente de escritorio habla con la API a través del TestClient de FastAPI (sin abrir
un puerto). Los diálogos se sustituyen por respuestas automáticas, como si un usuario
llenara el formulario y pulsara "Guardar".
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.cuadricula import DIAS, HORAS, Celda
from asi_cliente.views import catalogos as vista_catalogos
from asi_cliente.views import horarios as vista_horarios
from asi_cliente.views import periodos as vista_periodos
from asi_cliente.views.catalogos import DOCENTES, VistaCatalogo
from asi_cliente.views.horarios import DialogoCelda, VistaHorarios
from asi_cliente.views.periodos import VistaPeriodos
from asi_cliente.views.ventana_principal import VentanaPrincipal

CONTRASENA = "contrasena-de-prueba"  # igual que en conftest.py


def api_de(correo: str) -> ClienteApi:
    api = ClienteApi(http=TestClient(app))
    api.iniciar_sesion(correo, CONTRASENA)
    return api


@pytest.fixture
def api_admin(admin):
    return api_de(admin.correo)


@pytest.fixture
def api_consulta(consulta):
    return api_de(consulta.correo)


@pytest.fixture
def errores(monkeypatch):
    """Captura los mensajes de error en lugar de mostrar ventanas."""
    vistos: list = []
    for modulo in (vista_catalogos, vista_periodos, vista_horarios):
        monkeypatch.setattr(modulo, "mostrar_error", lambda _p, e, *_: vistos.append(e))
        monkeypatch.setattr(modulo, "confirmar", lambda *_a, **_k: True)
    return vistos


def responder_formulario(monkeypatch, modulo, *respuestas: dict):
    """Cada vez que la vista abra un formulario, se "llena" con la siguiente respuesta."""
    pendientes = list(respuestas)

    class FormularioAutomatico:
        def __init__(self, *_a, **_k):
            self.datos = None

        def exec(self):
            if not pendientes:
                return False
            self.datos = pendientes.pop(0)
            return True

        def valores(self):
            return self.datos

    monkeypatch.setattr(modulo, "DialogoFormulario", FormularioAutomatico)


# --- Docentes -------------------------------------------------------------------


def test_docentes_crear_editar_y_desactivar(qtbot, api_admin, admin, errores, monkeypatch):
    vista = VistaCatalogo(api_admin, api_admin.usuario, DOCENTES, "Docentes")
    qtbot.addWidget(vista)

    responder_formulario(
        monkeypatch,
        vista_catalogos,
        {"nombre": "Omega Prueba Ana", "nomina": "ZZ1", "correo": None},
    )
    vista.nuevo()
    assert [f["nombre"] for f in vista.tabla.filas] == ["OMEGA PRUEBA ANA"]
    assert vista.tabla.seleccionado()["nomina"] == "ZZ1"

    responder_formulario(
        monkeypatch,
        vista_catalogos,
        {"nombre": "OMEGA PRUEBA ANA", "nomina": "ZZ1", "correo": "ar@prueba.mx"},
    )
    vista.editar()
    assert vista.tabla.seleccionado()["correo"] == "ar@prueba.mx"

    vista.cambiar_estado()  # desactiva: desaparece de la lista de activos
    assert vista.tabla.filas == []
    vista.inactivos.setChecked(True)
    assert vista.tabla.filas[0]["activo"] is False
    assert errores == []


def test_docente_duplicado_muestra_error_y_permite_corregir(qtbot, api_admin, errores, monkeypatch):
    api_admin.post("/docentes", {"nombre": "KAPPA PRUEBA JUAN"})
    vista = VistaCatalogo(api_admin, api_admin.usuario, DOCENTES)
    qtbot.addWidget(vista)
    # Primero un duplicado (error), luego el usuario corrige el nombre en el mismo formulario.
    responder_formulario(
        monkeypatch,
        vista_catalogos,
        {"nombre": "kappa prueba juan"},
        {"nombre": "KAPPA PRUEBA JUANA"},
    )
    vista.nuevo()
    assert "ya existe" in str(errores[0])
    assert len(vista.tabla.filas) == 2


def test_consulta_no_ve_botones_de_edicion(qtbot, api_consulta):
    vista = VistaCatalogo(api_consulta, api_consulta.usuario, DOCENTES)
    qtbot.addWidget(vista)
    assert vista.boton_nuevo.isHidden() and vista.boton_estado.isHidden()


# --- Periodos ---------------------------------------------------------------------


def test_periodos_crear_activar_y_cerrar(qtbot, api_admin, errores, monkeypatch):
    vista = VistaPeriodos(api_admin, api_admin.usuario)
    qtbot.addWidget(vista)
    responder_formulario(
        monkeypatch,
        vista_periodos,
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    vista.nuevo()
    assert vista.tabla.seleccionado()["estado"] == "borrador"
    assert vista.boton_activar.isEnabled()

    vista.boton_activar.click()
    assert vista.tabla.seleccionado()["estado"] == "activo"
    vista.boton_cerrar.click()
    assert vista.tabla.seleccionado()["estado"] == "cerrado"
    assert not vista.boton_editar.isEnabled()
    assert errores == []


# --- Horarios ----------------------------------------------------------------------


@pytest.fixture
def datos(api_admin):
    periodo = api_admin.post(
        "/periodos",
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    api_admin.post(f"/periodos/{periodo['id']}/activar")
    return {
        "periodo": periodo,
        "docente": api_admin.post("/docentes", {"nombre": "DOCENTE PRUEBA UNO"}),
        "calculo": api_admin.post("/asignaturas", {"nombre": "CÁLC. DIF."}),
        "gestion": api_admin.post(
            "/asignaturas", {"nombre": "GESTIÓN ACADÉMICA", "tipo": "actividad"}
        ),
        "grupo": api_admin.post("/grupos", {"clave": "A"}),
        "aula": api_admin.post("/aulas", {"clave": "M01"}),
    }


def llenar_celda(monkeypatch, celda: Celda | None, horas: int = 1, vaciar: bool = False):
    class DialogoAutomatico:
        VACIAR = DialogoCelda.VACIAR

        def __init__(self, *_a, **_k):
            self.horas = type("Spin", (), {"value": staticmethod(lambda: horas)})()

        def exec(self):
            return DialogoCelda.VACIAR if vaciar else 1

        def celda(self):
            return celda

    monkeypatch.setattr(vista_horarios, "DialogoCelda", DialogoAutomatico)


def texto_celda(vista, dia: str, hora: int) -> str:
    item = vista.cuadricula.item(HORAS.index(hora), DIAS.index(dia))
    return item.text() if item else ""


def test_horario_flujo_completo_desde_la_interfaz(qtbot, api_admin, datos, errores, monkeypatch):
    vista = VistaHorarios(api_admin, api_admin.usuario)
    qtbot.addWidget(vista)
    assert "Sin horario" in vista.estado.text()

    vista.boton_nueva.click()
    assert vista.horario["version"] == 1 and vista.horario["estado"] == "borrador"

    # Lunes 7:00–9:00 CÁLC. DIF. grupo A, M01 (doble clic en la celda, 2 horas).
    llenar_celda(
        monkeypatch,
        Celda(datos["calculo"]["id"], datos["grupo"]["id"], datos["aula"]["id"]),
        horas=2,
    )
    vista.editar_celda(HORAS.index(7), DIAS.index("lunes"))
    assert "CÁLC. DIF." in texto_celda(vista, "lunes", 8)
    assert vista.boton_guardar.isEnabled() and not vista.boton_confirmar.isEnabled()

    vista.boton_guardar.click()
    assert errores == []
    assert vista.horario["horas"] == 2
    assert vista.boton_confirmar.isEnabled()

    vista.boton_confirmar.click()
    assert vista.horario["estado"] == "vigente"
    assert "para cambiarla crea una nueva versión" in vista.estado.text()
    assert not vista.boton_guardar.isEnabled()

    # Nueva versión: copia la vigente; se agrega una hora de gestión y se confirma.
    vista.boton_nueva.click()
    assert vista.horario["version"] == 2 and "CÁLC. DIF." in texto_celda(vista, "lunes", 7)
    llenar_celda(monkeypatch, Celda(datos["gestion"]["id"], None, datos["aula"]["id"]))
    vista.editar_celda(HORAS.index(9), DIAS.index("martes"))
    vista.boton_guardar.click()
    vista.boton_confirmar.click()

    estados = [(v["version"], v["estado"]) for v in vista.versiones.filas]
    assert estados == [(2, "vigente"), (1, "historico")]
    assert errores == []

    # La versión histórica se puede consultar y conserva sus datos originales.
    vista.versiones.seleccionar_id(vista.versiones.filas[1]["id"])
    assert vista.horario["version"] == 1 and texto_celda(vista, "martes", 9) == ""


def test_error_de_validacion_se_muestra_y_no_se_guarda(
    qtbot, api_admin, datos, errores, monkeypatch
):
    vista = VistaHorarios(api_admin, api_admin.usuario)
    qtbot.addWidget(vista)
    vista.boton_nueva.click()
    llenar_celda(monkeypatch, Celda(datos["calculo"]["id"], None, datos["aula"]["id"]))
    vista.editar_celda(0, 0)  # materia sin grupo
    vista.boton_guardar.click()
    assert errores and any("necesita grupo" in p for p in errores[0].problemas)
    assert vista.cambios_pendientes  # lo capturado no se pierde

    llenar_celda(monkeypatch, None, vaciar=True)
    vista.editar_celda(0, 0)
    assert texto_celda(vista, "lunes", 7) == ""


def test_consulta_ve_horarios_pero_no_edita(qtbot, api_admin, api_consulta, datos, monkeypatch):
    h = api_admin.post(
        "/horarios", {"docente_id": datos["docente"]["id"], "periodo_id": datos["periodo"]["id"]}
    )
    vista = VistaHorarios(api_consulta, api_consulta.usuario)
    qtbot.addWidget(vista)
    assert vista.horario["id"] == h["id"]
    assert vista.boton_nueva.isHidden() and vista.boton_confirmar.isHidden()
    llamado = []
    monkeypatch.setattr(vista_horarios, "DialogoCelda", lambda *a, **k: llamado.append(1))
    vista.editar_celda(0, 0)
    assert llamado == []  # el doble clic no abre el editor


def test_ventana_principal_abre_las_pantallas_nuevas(qtbot, api_admin, datos):
    ventana = VentanaPrincipal(api_admin.usuario, api_admin)
    qtbot.addWidget(ventana)
    assert isinstance(ventana.abrir_seccion("Horarios"), VistaHorarios)
    assert isinstance(ventana.abrir_seccion("Periodos"), VistaPeriodos)
    assert isinstance(ventana.abrir_seccion("Docentes"), VistaCatalogo)
    # La pantalla se crea una sola vez y se reutiliza.
    assert ventana.abrir_seccion("Horarios") is ventana.abrir_seccion("Horarios")
