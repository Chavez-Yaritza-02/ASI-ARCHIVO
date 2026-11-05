"""Diagnóstico HTTPS usando exactamente el cliente instalado y su almacén de confianza."""

import json
import sys
from pathlib import Path

from asi_cliente.api.cliente import ClienteApi, ErrorApi, validar_url
from asi_shared.version import PROTOCOLO


def ejecutar():
    url = sys.argv[sys.argv.index("--servidor") + 1]
    destino = Path(sys.argv[sys.argv.index("--resultado") + 1])
    api = None
    try:
        api = ClienteApi(validar_url(url, solo_https=True))
        datos = api.get("/sistema/identidad")
        if datos.get("producto") != "ASI-ARCHIVO" or datos.get("protocolo") != PROTOCOLO:
            raise ErrorApi("Servidor incompatible")
        salida, codigo = {"estado": "ok", "https": True}, 0
    except (ErrorApi, ValueError):
        salida, codigo = {"estado": "rechazado", "https": False}, 2
    finally:
        if api:
            api.cerrar()
    with destino.open("x", encoding="utf-8") as archivo:
        json.dump(salida, archivo)
    return codigo
