"""Arranque portable de las vistas Qt, sin PostgreSQL ni datos institucionales."""

import httpx
from PySide6.QtCore import QDate, QTime

from asi_cliente.api.cliente import ClienteApi, UsuarioSesion
from asi_cliente.views.asistencia_hora import VistaAsistenciaHora
from asi_cliente.views.consultas import (
    VistaBuscador,
    VistaConfiguracionAsistencia,
    VistaGrupos,
    VistaUbicacion,
)


def test_consultas_portables_sin_base_de_datos(qtbot):
    def responder(peticion):
        ruta = peticion.url.path
        if ruta in ("/periodos", "/consultas/grupos", "/docentes"):
            datos = []
        elif ruta == "/consultas/ahora":
            datos = {"fecha": "2026-11-02", "hora": "07:30:00", "zona": "America/Mexico_City"}
        elif ruta == "/configuracion/asistencia":
            datos = {"tolerancia_minutos": 10}
        elif ruta == "/bitacora/horas":
            metricas = (
                "programadas",
                "exigibles",
                "cumplidas",
                "faltantes",
                "justificadas",
                "pendientes",
                "suspendidas",
            )
            datos = {
                "fecha": "2026-11-02",
                "filas": [],
                "registros_fuera_de_programacion": [],
                "registros_por_turno_sin_convertir": [],
                "aviso": "Ficticio",
                "totales": {
                    "minutos": dict.fromkeys(metricas, 0),
                    "horas": dict.fromkeys(metricas, 0),
                },
            }
        elif ruta == "/buscador":
            datos = {
                k: {"total": 0, "resultados": []}
                for k in ("docentes", "materias", "grupos", "aulas", "actividades")
            }
        else:
            raise AssertionError(f"Ruta no esperada: {ruta}")
        return httpx.Response(200, json=datos)

    api = ClienteApi(transporte=httpx.MockTransport(responder))
    usuario = UsuarioSesion(
        1,
        "ficticio@prueba.mx",
        "Ficticio",
        ["consulta"],
        ["docentes.ver", "horarios.ver", "asistencia.ver"],
    )
    for clase in (
        VistaAsistenciaHora,
        VistaBuscador,
        VistaGrupos,
        VistaUbicacion,
        VistaConfiguracionAsistencia,
    ):
        vista = clase(api, usuario)
        qtbot.addWidget(vista)
        vista.show()
        qtbot.waitUntil(vista.isVisible)
        if isinstance(vista, VistaUbicacion):
            assert vista.fecha.date() == QDate(2026, 11, 2)
            assert vista.hora.time() == QTime(7, 30)
        if isinstance(vista, VistaGrupos):
            assert vista.boton_pdf.isHidden() and vista.boton_excel.isHidden()
        if isinstance(vista, VistaConfiguracionAsistencia):
            assert vista.minutos.value() == 10 and not vista.minutos.isEnabled()
