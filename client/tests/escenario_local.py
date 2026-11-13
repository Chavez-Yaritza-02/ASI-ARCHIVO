"""Escenario de la aplicación local en un proceso aparte (lo usa test_modo_local.py).

    python escenario_local.py <carpeta> primera|segunda

La red queda bloqueada: cualquier intento de conexión hace fallar el escenario. Imprime un
JSON con lo observado. Datos ficticios únicamente.
"""

import json
import socket
import sys
from pathlib import Path


def _sin_red(*_args, **_kwargs):
    raise AssertionError("La aplicación local intentó usar la red")


# Solo se permite conectar con sockets que este mismo proceso abrió: en Windows, asyncio
# crea así su canal interno (socketpair). Cualquier otro destino —internet o un servidor de
# esta computadora— hace fallar el escenario.
_propios: set = set()
_bind, _connect = socket.socket.bind, socket.socket.connect


def _bind_registrado(self, direccion):
    _bind(self, direccion)
    _propios.add(self.getsockname()[:2])


def _connect_interno(self, direccion):
    if tuple(direccion[:2]) not in _propios:
        _sin_red()
    return _connect(self, direccion)


socket.socket.bind = _bind_registrado
socket.socket.connect = _connect_interno
socket.socket.connect_ex = _sin_red
socket.create_connection = _sin_red
socket.getaddrinfo = _sin_red

from asi_cliente import local  # noqa: E402
from asi_cliente.api.cliente import ErrorApi  # noqa: E402

USUARIO, CLAVE, FECHA = "jefatura", "clave-ficticia-local", "2026-11-02"
FECHA_INCIDENCIA = "2026-11-09"


def excel_ficticio(carpeta: Path) -> bytes:
    """El mismo archivo en las dos fases (como un Excel guardado en la computadora)."""
    archivo = carpeta / "incidencias-ficticias.xlsx"
    if not archivo.exists():
        from openpyxl import Workbook

        libro = Workbook()
        libro.active.append(["FECHA", "DOCENTE", "INCIDENCIA"])
        libro.active.append(["09/11/2026", "Ficticio Local Docente", "FALTA"])
        libro.save(archivo)
    return archivo.read_bytes()


def importar_incidencia(api, contenido: bytes) -> int:
    """Falta del Excel ficticio: solo la hora de las 08:00 (la elegida, no toda la jornada)."""
    importacion = api.subir("/incidencias-excel", "incidencias-ficticias.xlsx", contenido, {})
    fila = importacion["filas"][0]
    horas = api.get(f"/incidencias-excel/filas/{fila['id']}/horas")["horas"]
    ocho = [
        {"bloque_id": h["bloque_id"], "programado_inicio": h["programado_inicio"]}
        for h in horas
        if h["programado_inicio"].startswith("08:00")
    ]
    api.patch(f"/incidencias-excel/filas/{fila['id']}", {"horas": ocho})
    return api.post(f"/incidencias-excel/{importacion['id']}/importar", {"filas": [fila["id"]]})[
        "horas"
    ]


def crear_escuela(api) -> None:
    def crear(ruta, datos):
        return api.post(ruta, datos)["id"]

    periodo = crear(
        "/periodos",
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    docente = crear("/docentes", {"nombre": "DOCENTE FICTICIO LOCAL"})
    materia = crear("/asignaturas", {"nombre": "CÁLC. DIF."})
    aula = crear("/aulas", {"clave": "M01"})
    grupo = crear("/grupos", {"letra": "A", "periodo_id": periodo, "carrera": "IEM", "semestre": 3})
    api.post(f"/periodos/{periodo}/activar")
    horario = api.post("/horarios", {"docente_id": docente, "periodo_id": periodo})["id"]
    bloque = {"dia": "lunes", "hora_inicio": "07:00", "hora_fin": "09:00"}
    bloque |= {"asignatura_id": materia, "grupo_id": grupo, "aula_id": aula}
    api.put(f"/horarios/{horario}/bloques", [bloque])
    api.post(f"/horarios/{horario}/confirmar", {"vigente_desde": "2026-08-01"})


def capturar(api, fila, estado):
    datos = {k: fila[k] for k in ("docente_id", "fecha", "bloque_id", "programado_inicio")}
    return api.post("/asistencias/horas", {**datos, "estado": estado})


def principal(carpeta: Path, fase: str) -> dict:
    abierta = local.iniciar(carpeta, clave="clave-de-sesiones-ficticia-" + "x" * 32)
    api = abierta.api
    salida = {"creada": abierta.creada, "base": str(abierta.base)}
    try:
        if fase == "primera":
            salida["estado_inicial"] = api.get("/local/estado")
            api.post(
                "/local/cuenta", {"usuario": USUARIO, "nombre": "Jefatura", "contrasena": CLAVE}
            )
            api.iniciar_sesion(USUARIO, CLAVE)
            crear_escuela(api)
            filas = api.get("/bitacora/horas", fecha=FECHA)["filas"]
            salida["registro"] = capturar(api, filas[0], "asistio")["estado"]
            capturar(api, filas[1], "falto")
            salida["incidencia_importada"] = importar_incidencia(api, excel_ficticio(carpeta))
        else:
            salida["estado_inicial"] = api.get("/local/estado")
            api.iniciar_sesion(USUARIO, CLAVE)
        filas = api.get("/bitacora/horas", fecha=FECHA)["filas"]
        salida["estados"] = [f["estado"] for f in filas]
        try:  # un segundo registro de la misma hora se rechaza
            capturar(api, filas[0], "retardo")
            salida["duplicado"] = "aceptado"
        except ErrorApi as error:
            salida["duplicado"] = error.estado
        salida["incidencia"] = [
            f["estado"] for f in api.get("/bitacora/horas", fecha=FECHA_INCIDENCIA)["filas"]
        ]
        repetido = api.subir(
            "/incidencias-excel", "otra-copia.xlsx", excel_ficticio(carpeta), {}
        )  # el mismo archivo no se duplica
        salida["excel_repetido"] = [repetido["ya_existia"], len(api.get("/incidencias-excel"))]
        salida["identidad"] = api.identidad()["tipo_servidor"]
        salida["sistema"] = api.get("/sistema/estado")["base_de_datos"]
    finally:
        abierta.cerrar()
    return salida


if __name__ == "__main__":
    print(json.dumps(principal(Path(sys.argv[1]), sys.argv[2])))
