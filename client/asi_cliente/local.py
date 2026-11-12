"""Modo local: la aplicación trabaja sola en esta computadora, sin servidor y sin internet.

Las mismas reglas de la API (FastAPI) corren **dentro** del programa: las pantallas les
hablan por un transporte en memoria, sin abrir puertos ni conexiones de red. Los datos
viven en una base SQLite y una carpeta de archivos de esta computadora:

    <carpeta>/datos/asi-archivo.db   base SQLite (diario WAL, escritura completa)
    <carpeta>/archivo/                PDF y justificantes del archivo digital
    <carpeta>/asi-archivo.lock        impide abrir dos ventanas sobre la misma base

<carpeta> es %LOCALAPPDATA%\\ASI-ARCHIVO en Windows (fuera de OneDrive y de la carpeta del
programa: desinstalar no la borra). ASI_DATOS_LOCALES la cambia (pruebas y ensayos).
"""

from __future__ import annotations

import os
import secrets
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from asi_cliente.api.cliente import ClienteApi

NOMBRE_BD = "asi-archivo.db"
DIRECCION_LOCAL = "http://esta-computadora"
SERVICIO_CLAVE = "ASI-ARCHIVO:clave-sesiones-local"


class ErrorLocal(Exception):
    """No se pudo abrir la aplicación local (mensaje para la persona usuaria)."""


def carpeta_datos() -> Path:
    if os.environ.get("ASI_DATOS_LOCALES"):
        return Path(os.environ["ASI_DATOS_LOCALES"]).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ASI-ARCHIVO"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ASI-ARCHIVO"
    return Path.home() / ".local" / "share" / "ASI-ARCHIVO"


def _clave_sesiones(carpeta: Path) -> str:
    """Clave que firma las sesiones, creada la primera vez.

    Se guarda en el llavero del sistema (en Windows, el Administrador de credenciales,
    protegido por DPAPI). Si no hay llavero, en un archivo privado dentro de la carpeta.
    Perderla solo obliga a iniciar sesión otra vez; no afecta a los datos.
    """
    cuenta = str(carpeta.resolve())
    with suppress(KeyringError):
        guardada = keyring.get_password(SERVICIO_CLAVE, cuenta)
        if guardada:
            return guardada
        nueva = secrets.token_urlsafe(48)
        keyring.set_password(SERVICIO_CLAVE, cuenta, nueva)
        if keyring.get_password(SERVICIO_CLAVE, cuenta) == nueva:
            return nueva
    archivo = carpeta / "datos" / ".clave-sesiones"
    if archivo.is_file():
        return archivo.read_text().strip()
    nueva = secrets.token_urlsafe(48)
    descriptor = os.open(archivo, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as f:
        f.write(nueva)
    return nueva


@dataclass
class AplicacionLocal:
    carpeta: Path
    base: Path
    api: ClienteApi
    creada: bool  # True si la base se creó en esta apertura
    interrumpidas: int = 0  # importaciones de OCR que quedaron a medias al cerrar
    _bloqueo: object | None = field(default=None, repr=False)

    def cerrar(self) -> None:
        """Termina las escrituras pendientes y libera la base y el bloqueo."""
        from app.core.config import obtener_configuracion
        from app.db.sesion import obtener_engine

        with suppress(Exception):
            self.api.cerrar()
        with suppress(Exception):
            engine = obtener_engine()
            with engine.connect() as conexion:
                # Vuelca el diario WAL a la base: el archivo queda completo por sí solo.
                conexion.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            engine.dispose()
        obtener_engine.cache_clear()
        obtener_configuracion.cache_clear()
        if self._bloqueo is not None:
            self._bloqueo.unlock()
            self._bloqueo = None


def _bloquear(carpeta: Path):
    """Una sola ventana a la vez sobre la misma base."""
    from PySide6.QtCore import QLockFile

    bloqueo = QLockFile(str(carpeta / "asi-archivo.lock"))
    bloqueo.setStaleLockTime(0)  # si el programa se cerró de golpe, el bloqueo se recupera
    if not bloqueo.tryLock(200):
        raise ErrorLocal(
            "ASI-ARCHIVO ya está abierto en esta computadora. Usa esa ventana; "
            "no se pueden abrir dos a la vez."
        )
    return bloqueo


def configurar_entorno(carpeta: Path, base: Path, clave: str) -> None:
    """Variables que leen las reglas de la API. No se lee el .env del servidor."""
    os.environ.update(
        {
            "ASI_MODO_LOCAL": "1",
            "ASI_ENTORNO": "local",
            "ASI_TIPO_SERVIDOR": "local",
            "ASI_DATABASE_URL": f"sqlite:///{base}",
            "ASI_SECRET_KEY": clave,
            "ASI_ARCHIVO_RAIZ": str(carpeta / "archivo"),
            "ASI_HOSTS_PERMITIDOS": "[]",
        }
    )
    # El instalador exige antivirus (etapa 4: Microsoft Defender); al desarrollar es opcional.
    os.environ.setdefault(
        "ASI_ARCHIVO_REQUERIR_ANTIVIRUS", "true" if getattr(sys, "frozen", False) else "false"
    )
    for variable in ("PGOPTIONS", "PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR"):
        os.environ.pop(variable, None)


def iniciar(
    carpeta: Path | None = None,
    *,
    nombre_bd: str = NOMBRE_BD,
    clave: str | None = None,
    bloquear: bool = True,
) -> AplicacionLocal:
    """Abre (o crea la primera vez) la base local y devuelve el cliente listo para usar."""
    carpeta = (carpeta or carpeta_datos()).expanduser().resolve()
    for sub in ("datos", "archivo"):
        (carpeta / sub).mkdir(parents=True, exist_ok=True)
    bloqueo = _bloquear(carpeta) if bloquear else None
    try:
        base = carpeta / "datos" / nombre_bd
        configurar_entorno(carpeta, base, clave or _clave_sesiones(carpeta))

        from app.core.config import obtener_configuracion
        from app.db.sesion import obtener_engine

        obtener_configuracion.cache_clear()
        obtener_engine.cache_clear()

        from app.db.sqlite_local import (
            BaseLocalIncompatible,
            marcar_importaciones_interrumpidas,
            preparar_base_local,
        )

        engine = obtener_engine()
        try:
            creada = preparar_base_local(engine)
        except BaseLocalIncompatible as error:
            raise ErrorLocal(f"{error}. Avisa al administrador.") from error
        interrumpidas = marcar_importaciones_interrumpidas(engine)

        from fastapi.testclient import TestClient

        from app.main import app

        # Transporte en memoria hacia las reglas de la API: no abre puertos ni usa la red.
        http = TestClient(app, base_url=DIRECCION_LOCAL, raise_server_exceptions=False)
        api = ClienteApi(http=http, servicio_llavero=f"ASI-ARCHIVO:local:{carpeta}")
        api.carpeta_local = carpeta
        return AplicacionLocal(carpeta, base, api, creada, interrumpidas, bloqueo)
    except BaseException:
        if bloqueo is not None:
            bloqueo.unlock()
        raise
