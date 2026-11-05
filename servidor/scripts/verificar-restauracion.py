"""Comprueba una copia restaurada contra su manifiesto, en BD de verificación."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg import sql


def verificar(raiz):
    if (os.environ.get("PGHOST"), os.environ.get("PGDATABASE")) != (
        "db-verificacion",
        "asi_archivo_verificacion",
    ):
        raise ValueError("Destino de verificación no autorizado")
    manifiesto = json.loads((raiz / "manifiesto.json").read_text())
    with psycopg.connect() as c:
        base = c.execute("SELECT current_database()").fetchone()[0]
        if base != "asi_archivo_verificacion":
            raise ValueError("Identidad de base incorrecta")
        assert (
            c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == manifiesto["esquema"]
        )
        for tabla, esperado in manifiesto["conteos"].items():
            real = c.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(tabla))
            ).fetchone()[0]
            if real != esperado:
                raise ValueError("Conteo inconsistente en " + tabla)
        for clave, huella, tamano in c.execute("SELECT clave,sha256,bytes FROM documento_version"):
            if not re.fullmatch(r"[0-9a-f]{32}", clave):
                raise ValueError("Clave insegura")
            p = raiz / "documentos" / clave
            if p.is_symlink() or p.stat().st_size != tamano:
                raise ValueError("Documento inválido")
            with p.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != huella:
                    raise ValueError("Huella de documento incorrecta")
    print("Restauración aislada comprobada: esquema, todos los conteos y documentos")


if __name__ == "__main__":
    verificar(Path(sys.argv[1]))
