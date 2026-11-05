"""Prueba del ejecutable con transporte ficticio; nunca utiliza servidor o llavero real."""

import json
import secrets
import sys
import tempfile
from pathlib import Path

import httpx

from asi_cliente.api.cliente import ClienteApi
from asi_cliente.views.configuracion_inicial import ConfiguracionInicial
from asi_cliente.views.ventana_principal import VentanaPrincipal
from asi_shared.version import PROTOCOLO, VERSION


def ejecutar(app):
    resultado = Path(sys.argv[sys.argv.index("--resultado") + 1])
    clave = secrets.token_urlsafe(24)
    permisos = [
        "horarios.ver",
        "docentes.ver",
        "asistencia.ver",
        "documentos.ver",
        "reportes.generar",
    ]
    llamadas = []

    def responder(p):
        ruta = p.url.path
        llamadas.append(ruta)
        if ruta == "/sistema/identidad":
            datos = {"producto": "ASI-ARCHIVO", "version": VERSION, "protocolo": PROTOCOLO}
        elif ruta == "/sistema/estado":
            datos = {"estado": "ok", "esquema": "compatible", "antivirus_configurado": True}
        elif ruta == "/auth/login":
            assert clave.encode() in p.content
            datos = {"access_token": secrets.token_urlsafe(32)}
        elif ruta == "/auth/yo":
            datos = {
                "id": 1,
                "correo": "ficticio@example.invalid",
                "nombre": "Prueba ficticia",
                "roles": ["consulta"],
                "permisos": permisos,
            }
        elif ruta in (
            "/periodos",
            "/docentes",
            "/asignaturas",
            "/grupos",
            "/aulas",
            "/consultas/grupos",
            "/documentos/categorias",
        ):
            datos = []
        elif ruta == "/documentos/estado":
            datos = {"limite_mb": 20, "cargas_habilitadas": False}
        elif ruta == "/documentos":
            datos = {"total": 0, "resultados": []}
        elif ruta == "/bitacora/horas":
            claves = [
                "programadas",
                "exigibles",
                "cumplidas",
                "faltantes",
                "justificadas",
                "pendientes",
                "suspendidas",
            ]
            datos = {
                "fecha": "2026-11-02",
                "filas": [],
                "registros_fuera_de_programacion": [],
                "registros_por_turno_sin_convertir": [],
                "aviso": "Datos ficticios",
                "totales": {"minutos": dict.fromkeys(claves, 0), "horas": dict.fromkeys(claves, 0)},
            }
        elif ruta == "/bitacora/horas/exportar":
            # Se comprueba transporte y escritura del cliente. El contenido del reporte
            # se valida con PDF/Excel reales en las pruebas de integración del servidor.
            return httpx.Response(200, content=b"%PDF-1.4\n%Reporte ficticio de transporte\n")
        else:
            raise AssertionError(f"Ruta ficticia no prevista: {ruta}")
        return httpx.Response(200, json=datos)

    def fabrica(url):
        return ClienteApi(url, transporte=httpx.MockTransport(responder))

    d = ConfiguracionInicial("https://ficticio.example.invalid", fabrica_api=fabrica)
    d.comprobar()
    assert d.url_validada
    d.correo.setText("ficticio@example.invalid")
    d.contrasena.setText(clave)
    d.autenticar()
    assert d.api.usuario and not d.contrasena.text()
    d.finalizar()
    ventana = VentanaPrincipal(d.api.usuario, d.api)
    ventana.show()
    pantallas = ["Horarios", "Asistencia por hora", "Horarios por grupo", "Documentos"]
    for nombre in pantallas:
        vista = ventana.abrir_seccion(nombre)
        app.processEvents()
        assert vista.isVisible()
    with tempfile.TemporaryDirectory(prefix="asi-autoprueba-") as temporal:
        vista = ventana.abrir_seccion("Asistencia por hora")
        destino = Path(temporal) / "reporte-ficticio.pdf"
        assert vista.exportar_a(destino, "pdf") and destino.read_bytes().startswith(b"%PDF-")
    ventana.close()
    d.api.cerrar()
    # Datos ficticios y resultado técnico; ningún token o contraseña sale al archivo.
    with resultado.open("x", encoding="utf-8") as archivo:
        json.dump(
            {
                "estado": "ok",
                "version": VERSION,
                "pantallas": pantallas,
                "login": True,
                "permisos": True,
                "exportacion": True,
                "transporte": "simulado-sin-red",
                "solicitudes": len(llamadas),
            },
            archivo,
        )
    return 0
