"""Pantallas de bitácora y calendario contra la API real (datos ficticios)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QDate, QTime

from app.main import app
from app.services import bitacora as servicio_bitacora
from asi_cliente.api.cliente import ClienteApi
from asi_cliente.views import bitacora as vista_bitacora
from asi_cliente.views import calendario as vista_calendario
from asi_cliente.views.bitacora import DialogoAsistencia, VistaBitacora
from asi_cliente.views.calendario import VistaCalendario

CONTRASENA = "contrasena-de-prueba"
HOY = date(2026, 11, 4)  # miércoles
LUNES = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(servicio_bitacora, "hoy", lambda: HOY)


def api_de(correo):
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
    calc = api.post("/asignaturas", {"nombre": "GESTIÓN", "tipo": "actividad"})["id"]
    for nombre, bloques in (
        ("DOCENTE PRUEBA UNO", [("lunes", "07:00", "09:00"), ("lunes", "15:00", "16:00")]),
        ("DOCENTE PRUEBA DOS", [("lunes", "08:00", "10:00")]),
    ):
        d = api.post("/docentes", {"nombre": nombre})["id"]
        h = api.post("/horarios", {"docente_id": d, "periodo_id": p["id"]})
        api.put(
            f"/horarios/{h['id']}/bloques",
            [
                {"dia": dia, "hora_inicio": i, "hora_fin": f, "asignatura_id": calc}
                for dia, i, f in bloques
            ],
        )
        api.post(f"/horarios/{h['id']}/confirmar", {"vigente_desde": "2026-08-01"})
    return api


@pytest.fixture
def silencio(monkeypatch):
    errores = []
    for modulo in (vista_bitacora, vista_calendario):
        monkeypatch.setattr(modulo, "mostrar_error", lambda _p, e, *_: errores.append(e))
        monkeypatch.setattr(modulo, "confirmar", lambda *_a, **_k: True)
    return errores


def abrir(qtbot, api, fecha=LUNES) -> VistaBitacora:
    vista = VistaBitacora(api, api.usuario)
    qtbot.addWidget(vista)
    vista.fecha.setDate(QDate(fecha.year, fecha.month, fecha.day))
    return vista


def estados(vista) -> list[str]:
    return [vista.tabla.item(i, 6).text() for i in range(vista.tabla.rowCount())]


def responder(monkeypatch, *respuestas):
    pendientes = list(respuestas)

    class Automatico:
        def __init__(self, *_a, **_k):
            self.actual = None

        def exec(self):
            if not pendientes:
                return False
            self.actual = pendientes.pop(0)
            return True

        def datos(self):
            return self.actual

    monkeypatch.setattr(vista_bitacora, "DialogoAsistencia", Automatico)


def test_registrar_corregir_e_historial(qtbot, api, silencio, monkeypatch):
    vista = abrir(qtbot, api)
    assert estados(vista) == ["Pendiente de verificar"] * 3
    assert "Pendiente de verificar: 3" in vista.resumen.text()

    vista.tabla.selectRow(0)  # orden alfabético: DOCENTE PRUEBA DOS, programado a las 08:00
    responder(
        monkeypatch,
        {
            "estado": "retardo",
            "hora_entrada": "08:20",
            "hora_salida": None,
            "observaciones": "",
            "justificacion": "",
        },
    )
    vista.boton_registrar.click()
    assert silencio == []
    assert estados(vista)[0] == "Retardo (+20 min)"
    assert vista.boton_historial.isEnabled()

    # Corrección de un día anterior por el administrador (tiene autorización).
    responder(
        monkeypatch,
        {
            "estado": "justificado",
            "hora_entrada": None,
            "hora_salida": None,
            "observaciones": "",
            "justificacion": "Cita médica",
            "motivo": "Presentó comprobante",
        },
    )
    vista.boton_registrar.click()
    assert estados(vista)[0] == "Justificado"
    vistos = []
    monkeypatch.setattr(
        vista_bitacora,
        "DialogoHistorial",
        lambda cambios, _p: type(
            "D", (), {"exec": lambda s: vistos.append([c["accion"] for c in cambios])}
        )(),
    )
    vista.boton_historial.click()
    assert vistos == [["registrar", "corregir"]]


def test_marcar_varios_como_asistio(qtbot, api, silencio):
    vista = abrir(qtbot, api)
    vista.tabla.selectAll()
    assert vista.boton_asistieron.isEnabled()
    vista.boton_asistieron.click()
    assert silencio == []
    assert estados(vista) == ["Asistió"] * 3
    assert not vista.boton_asistieron.isEnabled()  # ya no hay pendientes seleccionados


def test_dia_inhabil_y_exportar(qtbot, api, silencio, tmp_path):
    api.post(
        "/calendario",
        {
            "tipo": "inhabil",
            "fecha_inicio": LUNES.isoformat(),
            "fecha_fin": LUNES.isoformat(),
            "descripcion": "Día festivo",
        },
    )
    vista = abrir(qtbot, api)
    assert "no se generan faltas" in vista.aviso_dia.text()
    assert estados(vista) == ["Día inhábil"] * 3
    ruta = tmp_path / "bitacora.pdf"
    assert vista.exportar_a(ruta, "pdf") and ruta.read_bytes().startswith(b"%PDF")
    ruta = tmp_path / "bitacora.xlsx"
    assert vista.exportar_a(ruta, "xlsx") and ruta.read_bytes().startswith(b"PK")


def test_incidencia_desde_la_pantalla(qtbot, api, silencio, monkeypatch):
    vista = abrir(qtbot, api)

    class Incidencia:
        def __init__(self, *_a):
            self.veces = 0

        def exec(self):
            self.veces += 1
            return self.veces == 1

        def datos(self):
            return {
                "tipo": "permiso",
                "docente_id": None,
                "turno": None,
                "descripcion": "Junta de academia",
            }

    monkeypatch.setattr(vista_bitacora, "DialogoIncidencia", Incidencia)
    vista.boton_incidencia.click()
    assert silencio == []
    assert "Junta de academia" in vista.incidencias.text()


def test_consulta_solo_ve(qtbot, api, consulta):
    vista = abrir(qtbot, api_de(consulta.correo))
    assert len(estados(vista)) == 3
    for boton in (
        vista.boton_registrar,
        vista.boton_asistieron,
        vista.boton_incidencia,
        vista.boton_pdf,
    ):
        assert boton.isHidden()


def test_dialogo_de_asistencia_sugiere_retardo_y_exige_motivo(qtbot):
    fila = {
        "docente": {"id": 1, "nombre": "DOCENTE PRUEBA UNO"},
        "turno": "matutino",
        "programado_inicio": "07:00:00",
        "programado_fin": "09:00:00",
        "actividades": [],
        "dia_habil": True,
        "motivo_inhabil": "",
        "asistencia": None,
        "tolerancia_minutos": 10,
    }
    d = DialogoAsistencia(fila, LUNES)
    qtbot.addWidget(d)
    d.usar_entrada.setChecked(True)
    d.entrada.setTime(QTime(7, 30))
    assert "30 min" in d.aviso.text() and "retardo" in d.aviso.text()
    d.estado.setCurrentIndex(d.estado.findData("falto"))
    assert not d.entrada.isEnabled() and d.datos()["hora_entrada"] is None

    registro = {
        "estado": "asistio",
        "hora_entrada": "07:00:00",
        "hora_salida": None,
        "observaciones": "",
        "justificacion": "",
        "id": 1,
    }
    correccion = DialogoAsistencia({**fila, "asistencia": registro}, LUNES)
    qtbot.addWidget(correccion)
    correccion._aceptar()
    assert "motivo" in correccion.mensaje.text() and correccion.result() == 0


def test_calendario_crear_y_anular(qtbot, api, silencio, monkeypatch):
    vista = VistaCalendario(api, api.usuario)
    qtbot.addWidget(vista)
    respuestas = [
        {
            "tipo": "vacaciones",
            "fecha_inicio": "2026-12-14",
            "fecha_fin": "2026-12-31",
            "turno": None,
            "descripcion": "Invierno",
        }
    ]

    class Formulario:
        def __init__(self, *_a, **_k):
            self.datos = None

        def exec(self):
            if not respuestas:
                return False
            self.datos = respuestas.pop(0)
            return True

        def valores(self):
            return self.datos

    monkeypatch.setattr(vista_calendario, "DialogoFormulario", Formulario)
    vista.boton_nuevo.click()
    assert silencio == [] and vista.tabla.seleccionado()["descripcion"] == "Invierno"
    vista.boton_anular.click()
    assert vista.tabla.filas == []
    vista.anulados.setChecked(True)
    assert vista.tabla.filas[0]["activo"] is False
