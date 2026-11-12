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


socket.socket.connect = _sin_red
socket.socket.connect_ex = _sin_red
socket.create_connection = _sin_red
socket.getaddrinfo = _sin_red

from asi_cliente import local  # noqa: E402
from asi_cliente.api.cliente import ErrorApi  # noqa: E402

USUARIO, CLAVE, FECHA = "jefatura", "clave-ficticia-local", "2026-11-02"


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
        salida["identidad"] = api.identidad()["tipo_servidor"]
        salida["sistema"] = api.get("/sistema/estado")["base_de_datos"]
    finally:
        abierta.cerrar()
    return salida


if __name__ == "__main__":
    print(json.dumps(principal(Path(sys.argv[1]), sys.argv[2])))
