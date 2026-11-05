"""Preparación no destructiva y copia íntegra de documentos exclusivamente ficticios."""

import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def modulo(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / archivo)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "dominio", ["../fuera", "ejemplo;orden", "https://ejemplo.invalid", "ejemplo\ninvalido"]
)
def test_preparar_rechaza_dominios_sin_crear_archivos(tmp_path, dominio):
    m = modulo("preparar_asi", "servidor/preparar.py")
    with pytest.raises(ValueError):
        m.preparar(tmp_path, dominio, "internal")
    assert not list(tmp_path.iterdir())


def test_preparar_no_sobrescribe_y_separa_secretos(tmp_path):
    m = modulo("preparar_asi", "servidor/preparar.py")
    (tmp_path / ".env.ejemplo").write_text("ASI_DOMINIO=ejemplo.invalid\nASI_TLS=internal\n")
    m.preparar(tmp_path, "localhost", "internal")
    secretos = tmp_path / ".secretos"
    assert len({p.read_text() for p in secretos.iterdir()}) == 6
    if os.name == "posix":
        assert secretos.stat().st_mode & 0o077 == 0
    original = (tmp_path / ".env").read_bytes()
    with pytest.raises(ValueError):
        m.preparar(tmp_path, "otro.invalid", "internal")
    assert (tmp_path / ".env").read_bytes() == original


def test_copia_verifica_huella_y_rechaza_rutas(tmp_path):
    m = modulo("copia_asi", "servidor/scripts/copia_consistente.py")
    origen = tmp_path / "origen"
    destino = tmp_path / "destino"
    origen.mkdir()
    destino.mkdir()
    clave = "a" * 32
    contenido = b"documento completamente ficticio"
    (origen / clave).write_bytes(contenido)
    m.copiar_documento(
        origen, destino, clave, hashlib.sha256(contenido).hexdigest(), len(contenido)
    )
    assert (destino / clave).read_bytes() == contenido
    with pytest.raises(ValueError):
        m.copiar_documento(origen, destino, "../fuera", "", 0)
    otro = "b" * 32
    (origen / otro).write_bytes(b"alterado")
    with pytest.raises(ValueError):
        m.copiar_documento(origen, destino, otro, "0" * 64, 8)
