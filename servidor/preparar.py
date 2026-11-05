"""Crear configuración NUEVA sin iniciar Docker ni migrar una base."""

import argparse
import os
import re
import secrets
from pathlib import Path


def preparar(raiz, dominio, tls):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}", dominio):
        raise ValueError("Dominio o dirección inválidos; no incluyas https://, rutas o puertos")
    if tls != "internal" and not re.fullmatch(r"[^\s{}$#]+@[^\s{}$#]+\.[^\s{}$#]+", tls):
        raise ValueError("TLS requiere 'internal' o un correo para el certificado público")
    if (raiz / ".env").exists() or (raiz / ".secretos").exists():
        raise ValueError(
            "Configuración existente: no se sobrescribe. Consulta el procedimiento de actualización"
        )
    os.umask(0o077)
    carpeta = raiz / ".secretos"
    carpeta.mkdir(mode=0o700)
    for nombre in (
        "db_admin",
        "db_app",
        "db_respaldo",
        "db_verificacion",
        "api_jwt",
        "backup_password",
    ):
        p = carpeta / nombre
        with p.open("x") as f:
            f.write(secrets.token_hex(32) + "\n")
        # Bind secrets de Compose: archivos legibles SOLO por los contenedores que los
        # montan. El directorio padre 0700 impide el acceso de otros usuarios del host.
        p.chmod(0o444)
    plantilla = (raiz / ".env.ejemplo").read_text()
    plantilla = re.sub(r"^ASI_DOMINIO=.*$", "ASI_DOMINIO=" + dominio, plantilla, flags=re.M)
    plantilla = re.sub(r"^ASI_TLS=.*$", "ASI_TLS=" + tls, plantilla, flags=re.M)
    with (raiz / ".env").open("x") as f:
        f.write(plantilla)
    (raiz / "respaldos").mkdir(mode=0o700, exist_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dominio", required=True)
    p.add_argument("--tls", required=True)
    a = p.parse_args()
    preparar(Path(__file__).parent, a.dominio, a.tls)
    print("Configuración creada. No se inició ningún servicio ni se conectó a ninguna base.")
