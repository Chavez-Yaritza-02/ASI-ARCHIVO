"""Dump, conteos y documentos de una misma instantánea. No altera la base origen."""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql


def copiar_documento(origen, destino, clave, huella, tamano):
    if not re.fullmatch(r"[0-9a-f]{32}", clave):
        raise ValueError("Clave de documento insegura")
    fd = os.open(origen / clave, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest = hashlib.sha256()
    total = 0
    with os.fdopen(fd, "rb") as entrada, (destino / clave).open("xb") as salida:
        if not stat.S_ISREG(os.fstat(entrada.fileno()).st_mode):
            raise ValueError("El documento no es un archivo regular")
        while bloque := entrada.read(1024 * 1024):
            total += len(bloque)
            if total > tamano:
                raise ValueError("Documento de tamaño inconsistente")
            digest.update(bloque)
            salida.write(bloque)
    if total != tamano or digest.hexdigest() != huella:
        raise ValueError("Documento corrupto: no se publica el respaldo")


def capturar(destino, origen):
    destino.mkdir(mode=0o700, parents=True, exist_ok=False)
    documentos = destino / "documentos"
    documentos.mkdir(mode=0o700)
    with psycopg.connect() as conexion:
        conexion.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = conexion.execute("SELECT pg_export_snapshot()").fetchone()[0]
        revision = conexion.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tablas = conexion.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
        ).fetchall()
        conteos = {
            nombre: conexion.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(nombre))
            ).fetchone()[0]
            for (nombre,) in tablas
        }
        versiones = conexion.execute(
            "SELECT clave,sha256,bytes FROM documento_version ORDER BY id"
        ).fetchall()
        subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--snapshot",
                snapshot,
                "--file",
                str(destino / "base.dump"),
            ],
            check=True,
        )
        for clave, huella, tamano in versiones:
            copiar_documento(origen, documentos, clave, huella, tamano)
        # El marcador de asociación se conserva; al cambiar de host/base se revisa explícitamente.
        marcador = origen / ".asi-archivo-almacen"
        if marcador.is_symlink():
            raise ValueError("Marcador inseguro")
        if marcador.is_file():
            shutil.copyfile(marcador, documentos / marcador.name)
        manifiesto = {
            "producto": "ASI-ARCHIVO",
            "formato": 1,
            "esquema": revision,
            "fecha_utc": datetime.now(UTC).isoformat(),
            "conteos": conteos,
            "documentos": [{"clave": c, "sha256": h, "bytes": n} for c, h, n in versiones],
        }
        (destino / "manifiesto.json").write_text(json.dumps(manifiesto), encoding="utf-8")


if __name__ == "__main__":
    capturar(Path(sys.argv[1]), Path("/datos/documentos"))
