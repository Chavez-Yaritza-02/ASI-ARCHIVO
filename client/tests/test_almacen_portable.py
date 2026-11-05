"""Permisos nativos del almacén en macOS/Windows, sin conexión a base de datos."""

import hashlib
from types import SimpleNamespace

import pytest

from app.archivos import almacen
from app.services.comun import ErrorNegocio


def test_almacen_privado_portable(tmp_path, monkeypatch):
    ruta = tmp_path / "privado"
    ruta.mkdir(mode=0o700)
    (ruta / ".asi-archivo-pruebas").write_text("ASI-ARCHIVO-PRUEBAS")
    cfg = SimpleNamespace(
        archivo_raiz=ruta,
        archivo_max_mb=1,
        archivo_antivirus_cmd=None,
        archivo_requerir_antivirus=False,
        entorno="pruebas",
    )
    monkeypatch.setattr(almacen, "obtener_configuracion", lambda: cfg)
    contenido = b"Objeto ficticio de prueba de permisos, sin documento real"
    clave = almacen.guardar(contenido)
    v = SimpleNamespace(
        clave=clave, bytes=len(contenido), sha256=hashlib.sha256(contenido).hexdigest()
    )
    assert almacen.leer(v) == contenido
    assert len(clave) == 32 and not clave.endswith(".pdf")
    with pytest.raises(ErrorNegocio):
        almacen.ruta_objeto("../fuera")
