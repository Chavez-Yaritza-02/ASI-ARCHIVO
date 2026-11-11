"""Modo local: la aplicación guarda todo en esta computadora, sin servidor aparte.

Al abrirse, la aplicación arranca por dentro la misma API del servidor central (solo
accesible desde esta computadora, en 127.0.0.1) con una base SQLite y una carpeta de
documentos. Todas las pantallas siguen hablando con la API igual que antes.

Carpeta de datos (se puede cambiar con la variable ASI_DATOS):
    Windows: C:\\ASI-ARCHIVO-DATOS      macOS/Linux: ~/ASI-ARCHIVO-DATOS
    ├── asi.db         maestros, horarios, asistencias, usuarios…
    └── documentos/    archivos PDF e imágenes del archivo digital
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

import httpx

NOMBRE_BASE = "asi.db"
CARPETA_DOCUMENTOS = "documentos"
ARCHIVO_CLAVE = ".clave-sesiones"
RESTAURACION_PENDIENTE = "restaurar-al-abrir.zip"
PREFIJO_RESPALDO = "ASI-ARCHIVO-respaldo"


class ErrorLocal(Exception):
    """Problema del modo local explicado para la persona que usa la aplicación."""


# --- carpeta de datos -------------------------------------------------------------


def carpeta_datos() -> Path:
    if os.environ.get("ASI_DATOS"):
        return Path(os.environ["ASI_DATOS"]).expanduser().resolve()
    if os.name == "nt":
        # Fuera de Documentos/Escritorio a propósito: OneDrive los sincroniza y una base
        # de datos sincronizada mientras está abierta se puede dañar.
        return Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\") / "ASI-ARCHIVO-DATOS"
    return Path.home() / "ASI-ARCHIVO-DATOS"


def _clave_sesiones(datos: Path) -> str:
    """Clave para firmar las sesiones; se crea una vez por computadora."""
    ruta = datos / ARCHIVO_CLAVE
    if ruta.is_file():
        clave = ruta.read_text().strip()
        if len(clave) >= 32:
            return clave
    clave = secrets.token_urlsafe(48)
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as archivo:
        archivo.write(clave)
    return clave


def _tesseract_incluido() -> Path | None:
    """Lector de texto (OCR) que trae el instalador de Windows, si existe."""
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for ruta in (base / "tesseract" / "tesseract.exe", base / "tesseract" / "tesseract"):
        if ruta.is_file():
            return ruta
    return None


def configurar_entorno(datos: Path) -> None:
    """Configura la API para el modo local. Debe llamarse ANTES de importar `app`."""
    datos.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "ASI_ENTORNO": "local",
            "ASI_TIPO_SERVIDOR": "local",
            "ASI_DATABASE_URL": f"sqlite:///{(datos / NOMBRE_BASE).as_posix()}",
            "ASI_SECRET_KEY": _clave_sesiones(datos),
            "ASI_ARCHIVO_RAIZ": str(datos / CARPETA_DOCUMENTOS),
            "ASI_ARCHIVO_REQUERIR_ANTIVIRUS": "false",
            "ASI_ARCHIVO_USAR_DEFENDER": "true",
        }
    )
    tesseract = _tesseract_incluido()
    if tesseract and not os.environ.get("ASI_TESSERACT_CMD"):
        os.environ["ASI_TESSERACT_CMD"] = str(tesseract)
        os.environ.setdefault("TESSDATA_PREFIX", str(tesseract.parent / "tessdata"))


# --- servidor interno ---------------------------------------------------------------


class ServidorLocal:
    """La API corriendo en un hilo de esta misma aplicación, solo en 127.0.0.1."""

    def __init__(self) -> None:
        self._servidor = None
        self._hilo: threading.Thread | None = None
        self.puerto: int | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}"

    def iniciar(self, espera_segundos: float = 30) -> None:
        import uvicorn
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        from app.main import app

        # Solo acepta peticiones dirigidas a esta misma computadora (evita que una página
        # web abierta en el navegador pueda hablar con la API usando otro nombre).
        protegida = TrustedHostMiddleware(app, allowed_hosts=["127.0.0.1"])

        enchufe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        enchufe.bind(("127.0.0.1", 0))  # el sistema elige un puerto libre
        self.puerto = enchufe.getsockname()[1]
        configuracion = uvicorn.Config(
            protegida,
            log_config=None,  # sin consola en Windows: no configurar salida a terminal
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        self._servidor = uvicorn.Server(configuracion)
        self._hilo = threading.Thread(
            target=self._servidor.run, kwargs={"sockets": [enchufe]}, daemon=True
        )
        self._hilo.start()
        limite = time.monotonic() + espera_segundos
        while not self._servidor.started:
            if not self._hilo.is_alive() or time.monotonic() > limite:
                raise ErrorLocal("No se pudo iniciar el motor interno de la aplicación")
            time.sleep(0.05)

    def detener(self) -> None:
        if self._servidor is None:
            return
        self._servidor.should_exit = True
        if self._hilo is not None:
            self._hilo.join(timeout=10)
        self._servidor = self._hilo = None
        from app.db.sesion import obtener_engine

        obtener_engine().dispose()  # cierra el archivo de la base

    def cliente_http(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.url,
            timeout=httpx.Timeout(300, connect=8),
            trust_env=False,  # nunca pasar por un proxy para hablar consigo misma
        )


def preparar(datos: Path) -> tuple[ServidorLocal, bool]:
    """Aplica una restauración pendiente, crea la base si hace falta y arranca la API.

    Devuelve el servidor y si ya existe al menos un usuario.
    """
    aplicar_restauracion_pendiente(datos)
    configurar_entorno(datos)
    from app.db.sesion import obtener_engine
    from app.local import hay_usuarios, preparar_base

    engine = obtener_engine()
    preparar_base(engine)
    servidor = ServidorLocal()
    servidor.iniciar()
    return servidor, hay_usuarios(engine)


def crear_administrador(correo: str, nombre: str, contrasena: str) -> None:
    from app.db.sesion import obtener_engine
    from app.local import crear_administrador as crear

    crear(obtener_engine(), correo, nombre, contrasena)


# --- respaldos ------------------------------------------------------------------------


def hacer_respaldo(datos: Path, destino: Path) -> Path:
    """Copia la base y los documentos a un .zip dentro de `destino` (USB, Drive…).

    La base se copia con la función de respaldo de SQLite, así la copia es consistente
    aunque la aplicación esté abierta.
    """
    base = datos / NOMBRE_BASE
    if not base.is_file():
        raise ErrorLocal("Todavía no hay información que respaldar")
    destino.mkdir(parents=True, exist_ok=True)
    nombre = f"{PREFIJO_RESPALDO}-{datetime.now():%Y-%m-%d-%H%M}.zip"
    final = destino / nombre
    temporal = destino / (nombre + ".incompleto")
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / NOMBRE_BASE
        origen = sqlite3.connect(base)
        try:
            with sqlite3.connect(copia) as salida:
                origen.backup(salida)
            salida.close()
        finally:
            origen.close()
        try:
            with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(copia, NOMBRE_BASE)
                documentos = datos / CARPETA_DOCUMENTOS
                if documentos.is_dir():
                    for archivo in sorted(documentos.rglob("*")):
                        if archivo.is_file() and not archivo.is_symlink():
                            relativo = archivo.relative_to(datos).as_posix()
                            zipf.write(archivo, relativo)
            _verificar_zip(temporal)
            temporal.replace(final)
        except BaseException:
            temporal.unlink(missing_ok=True)
            raise
    return final


def _verificar_zip(ruta: Path) -> None:
    """Comprueba que el .zip sea un respaldo de ASI-ARCHIVO íntegro y seguro de extraer."""
    try:
        with zipfile.ZipFile(ruta) as zipf:
            nombres = zipf.namelist()
            for nombre in nombres:
                partes = PurePosixPath(nombre).parts
                if (
                    nombre.startswith(("/", "\\"))
                    or ".." in partes
                    or ":" in nombre
                    or (nombre != NOMBRE_BASE and partes[:1] != (CARPETA_DOCUMENTOS,))
                ):
                    raise ErrorLocal("El archivo no es un respaldo válido de ASI-ARCHIVO")
            if NOMBRE_BASE not in nombres:
                raise ErrorLocal("El archivo no es un respaldo de ASI-ARCHIVO")
            if zipf.testzip() is not None:
                raise ErrorLocal("El respaldo está dañado")
            with tempfile.TemporaryDirectory() as tmp:
                zipf.extract(NOMBRE_BASE, tmp)
                conexion = sqlite3.connect(Path(tmp) / NOMBRE_BASE)
                try:
                    resultado = conexion.execute("PRAGMA integrity_check").fetchone()[0]
                    tablas = {
                        f[0]
                        for f in conexion.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                finally:
                    conexion.close()
                if resultado != "ok" or not {"usuario", "docente", "horario"} <= tablas:
                    raise ErrorLocal("La base de datos del respaldo está dañada")
    except zipfile.BadZipFile as error:
        raise ErrorLocal("El archivo no es un .zip válido") from error


def programar_restauracion(datos: Path, respaldo: Path) -> None:
    """Deja el respaldo listo para aplicarse la próxima vez que se abra la aplicación
    (no se puede reemplazar la base mientras está en uso)."""
    _verificar_zip(respaldo)
    shutil.copy2(respaldo, datos / RESTAURACION_PENDIENTE)


def aplicar_restauracion_pendiente(datos: Path) -> Path | None:
    """Reemplaza los datos por el respaldo pendiente. Los datos actuales NO se borran:
    se guardan en una carpeta «ASI-ARCHIVO-DATOS-antes-de-restaurar-<fecha>»."""
    pendiente = datos / RESTAURACION_PENDIENTE
    if not pendiente.is_file():
        return None
    _verificar_zip(pendiente)
    anterior = datos.parent / f"{datos.name}-antes-de-restaurar-{datetime.now():%Y%m%d-%H%M%S}"
    anterior.mkdir()
    for nombre in (NOMBRE_BASE, f"{NOMBRE_BASE}-wal", f"{NOMBRE_BASE}-shm", CARPETA_DOCUMENTOS):
        if (datos / nombre).exists():
            shutil.move(str(datos / nombre), anterior / nombre)
    with zipfile.ZipFile(pendiente) as zipf:
        zipf.extractall(datos)
    pendiente.unlink()
    return anterior


# --- autoprueba del ejecutable instalado ------------------------------------------------


def autoprueba(resultado: Path) -> int:
    """Comprueba el modo local en el .exe instalado (lo usa GitHub Actions).

    Usa la carpeta de ASI_DATOS (debe ser temporal y vacía) y datos ficticios.
    """
    import io
    import json

    from asi_cliente.api.cliente import ClienteApi

    pasos: list[str] = []
    servidor = None
    try:
        datos = carpeta_datos()
        servidor, hay_usuarios = preparar(datos)
        pasos.append("base y API interna")
        if hay_usuarios:
            raise ErrorLocal("La autoprueba requiere una carpeta de datos nueva (ASI_DATOS)")
        contrasena = secrets.token_urlsafe(16)
        crear_administrador("autoprueba@ejemplo.mx", "Autoprueba", contrasena)
        api = ClienteApi(http=servidor.cliente_http())
        api.iniciar_sesion("autoprueba@ejemplo.mx", contrasena)
        estado = api.get("/sistema/estado")
        if estado.get("estado") != "ok":
            raise ErrorLocal(f"La API interna no está lista: {estado}")
        api.post(
            "/periodos",
            {"nombre": "PERIODO FICTICIO", "fecha_inicio": "2099-01-10", "fecha_fin": "2099-06-30"},
        )
        api.cerrar()
        pasos.append("primer usuario, inicio de sesión y captura")

        from PIL import Image

        from app.archivos.almacen import validar

        imagen = io.BytesIO()
        Image.new("RGB", (40, 20), "white").save(imagen, "PNG")
        revisado = validar(imagen.getvalue(), "prueba.png", "image/png")
        if revisado["mime"] != "image/png":
            raise ErrorLocal("El procesador de documentos falló")
        pasos.append("procesador de documentos aislado")

        if os.environ.get("ASI_TESSERACT_CMD"):
            import pytesseract

            import app.importers.ocr  # noqa: F401 - configura la ruta de Tesseract

            idiomas = set(pytesseract.get_languages(config=""))
            if not {"spa", "eng"} <= idiomas:
                raise ErrorLocal(f"Faltan idiomas del lector de PDF: {idiomas}")
            pasos.append("lector de PDF con español e inglés")
        else:
            raise ErrorLocal("El instalador no incluye el lector de PDF (Tesseract)")

        respaldo = hacer_respaldo(datos, datos.parent / f"{datos.name}-respaldos")
        pasos.append(f"respaldo {respaldo.name}")
        salida = {"estado": "ok", "pasos": pasos}
        codigo = 0
    except BaseException as error:  # el resultado debe escribirse siempre
        salida = {"estado": "error", "pasos": pasos, "detalle": f"{type(error).__name__}: {error}"}
        codigo = 1
    finally:
        if servidor is not None:
            servidor.detener()
    resultado.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return codigo
