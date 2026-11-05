"""Almacén privado fuera del repositorio; claves opacas y verificación de integridad."""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path

from app.core.config import RAIZ_PROYECTO, obtener_configuracion
from app.db.proteccion_pruebas import en_pruebas
from app.services.comun import ErrorNegocio

EXTENSIONES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def _identidad_almacen():
    if en_pruebas():
        return "ASI-ARCHIVO-ALMACEN-V1-PRUEBAS"
    from sqlalchemy.engine import make_url

    url = make_url(obtener_configuracion().database_url)
    identidad = json.dumps([url.host, url.port or 5432, url.database])
    return "ASI-ARCHIVO-ALMACEN-V1:" + hashlib.sha256(identidad.encode()).hexdigest()


def raiz():
    directorio = obtener_configuracion().archivo_raiz.expanduser()
    if not directorio.is_absolute() or directorio.is_symlink():
        raise ErrorNegocio(
            "El almacén requiere una ruta absoluta privada sin enlaces simbólicos", 503
        )
    real = directorio.resolve()
    if (
        real.is_relative_to(RAIZ_PROYECTO.resolve())
        or RAIZ_PROYECTO.resolve().is_relative_to(real)
        or real in (Path.home().resolve(), Path(tempfile.gettempdir()).resolve())
    ):
        raise ErrorNegocio("El almacén debe quedar fuera del repositorio", 503)
    if en_pruebas():
        marcador = real / ".asi-archivo-pruebas"
        if (
            not real.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or not marcador.is_file()
            or marcador.is_symlink()
            or marcador.read_text() != "ASI-ARCHIVO-PRUEBAS"
        ):
            raise ErrorNegocio("Pruebas bloqueadas: almacén no autorizado", 503)
    real.mkdir(parents=True, exist_ok=True, mode=0o700)
    identidad = real / ".asi-archivo-almacen"
    if identidad.is_symlink():
        raise ErrorNegocio("Marcador de almacén no permitido", 503)
    if not identidad.exists() and any(p.name != ".asi-archivo-pruebas" for p in real.iterdir()):
        raise ErrorNegocio(
            "Usa una carpeta dedicada vacía, no una carpeta con archivos existentes", 503
        )
    esperado = _identidad_almacen()
    if identidad.exists() and identidad.read_text() != esperado:
        raise ErrorNegocio("La carpeta no corresponde a este almacén", 503)
    if os.name == "posix":
        if real.stat().st_uid != os.getuid():
            raise ErrorNegocio("El almacén no pertenece al usuario del servicio", 503)
        real.chmod(0o700)
    elif os.name == "nt":
        _privacidad_windows(real)
    if not identidad.exists():
        try:
            fd = os.open(identidad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as marcador:
                marcador.write(esperado)
        except FileExistsError:
            if identidad.read_text() != esperado:
                raise ErrorNegocio("No se pudo verificar el almacén", 503) from None
    return real


def _privacidad_windows(ruta):
    """DACL protegida: solo la identidad del servicio; los archivos la heredan."""
    powershell = (
        Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    script = (
        "$ErrorActionPreference='Stop'; "
        "$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
        "$acl=New-Object System.Security.AccessControl.DirectorySecurity; "
        "$acl.SetSecurityDescriptorSddlForm(('D:P(A;OICI;FA;;;'+$sid+')'), "
        "[System.Security.AccessControl.AccessControlSections]::Access); "
        "Set-Acl -LiteralPath $env:ASI_ARCHIVO_ACL_DESTINO -AclObject $acl; "
        "$aplicado=Get-Acl -LiteralPath $env:ASI_ARCHIVO_ACL_DESTINO; "
        "$reglas=$aplicado.GetAccessRules($true,$true,"
        "[System.Security.Principal.SecurityIdentifier]); "
        "if ((-not $aplicado.AreAccessRulesProtected) -or ($reglas.Count -ne 1) -or "
        "($reglas[0].IdentityReference.Value -ne $sid) -or "
        "($reglas[0].AccessControlType -ne "
        "[System.Security.AccessControl.AccessControlType]::Allow) "
        "-or ($reglas[0].FileSystemRights -ne "
        "[System.Security.AccessControl.FileSystemRights]::FullControl)) "
        "{ throw 'No se pudo verificar la DACL privada' }"
    )
    try:
        resultado = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "ASI_ARCHIVO_ACL_DESTINO": str(ruta)},
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ErrorNegocio("No se pudo proteger el almacén con permisos NTFS", 503) from error
    if resultado.returncode:
        detalle = resultado.stderr.decode(errors="replace")[:2000]
        raise ErrorNegocio(
            "El almacén requiere un volumen NTFS con permisos privados", 503
        ) from RuntimeError(detalle)


def nombre_seguro(nombre):
    nombre = unicodedata.normalize("NFC", nombre or "")
    if (
        not 1 <= len(nombre) <= 200
        or any(unicodedata.category(c).startswith("C") for c in nombre)
        or any(c in nombre for c in ("/", "\\", ":"))
        or nombre.strip() != nombre
        or Path(nombre).suffix.lower() not in EXTENSIONES
        or Path(nombre).stem.upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *[f"COM{i}" for i in range(1, 10)],
            *[f"LPT{i}" for i in range(1, 10)],
        }
    ):
        raise ErrorNegocio("Nombre o extensión de archivo no permitido", 422)
    return nombre


def _proceso(contenido, pagina=None):
    env = {
        k: v
        for k, v in os.environ.items()
        if k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG")
    }
    comando = [sys.executable, "-I", str(Path(__file__).with_name("procesador.py"))]
    if pagina is not None:
        comando.append(str(pagina))
    try:
        proceso = subprocess.run(comando, input=contenido, capture_output=True, timeout=15, env=env)
    except subprocess.TimeoutExpired as error:
        raise ErrorNegocio("El archivo excede el tiempo permitido de procesamiento", 422) from error
    if proceso.returncode or len(proceso.stdout) > 8 * 1024 * 1024:
        raise ErrorNegocio("Archivo inválido, cifrado o con contenido activo no permitido", 422)
    return proceso.stdout


def validar(contenido, nombre, mime):
    nombre = nombre_seguro(nombre)
    limite = obtener_configuracion().archivo_max_mb * 1024 * 1024
    if not contenido or len(contenido) > limite:
        raise ErrorNegocio("Archivo vacío o demasiado grande", 413)
    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in contenido:
        raise ErrorNegocio("Archivo rechazado por contenido no permitido", 422)
    datos = json.loads(_proceso(contenido))
    if datos["mime"] != EXTENSIONES[Path(nombre).suffix.lower()] or mime not in (
        datos["mime"],
        "application/octet-stream",
        None,
    ):
        raise ErrorNegocio("La extensión, el tipo declarado y el contenido no coinciden", 422)
    return {
        **datos,
        "nombre_original": nombre,
        "sha256": hashlib.sha256(contenido).hexdigest(),
        "bytes": len(contenido),
    }


def _antivirus(ruta):
    cfg = obtener_configuracion()
    if not cfg.archivo_antivirus_cmd:
        if cfg.archivo_requerir_antivirus or cfg.entorno not in ("pruebas", "desarrollo"):
            raise ErrorNegocio("Configura el antivirus local antes de cargar documentos", 503)
        return
    comando = cfg.archivo_antivirus_cmd
    if not comando.is_absolute() or not comando.is_file():
        raise ErrorNegocio("El antivirus local no está disponible", 503)
    try:
        proceso = subprocess.run(
            [str(comando), "--no-summary", "--", str(ruta)], capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ErrorNegocio("No fue posible completar el análisis antivirus", 503) from error
    if proceso.returncode == 1:
        raise ErrorNegocio("El antivirus rechazó el archivo", 422)
    if proceso.returncode != 0:
        raise ErrorNegocio("El antivirus no pudo comprobar el archivo", 503)


def guardar(contenido):
    directorio = raiz()
    clave = uuid.uuid4().hex
    ruta = directorio / clave
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(ruta, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as archivo:
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        _antivirus(ruta)
        with ruta.open("rb") as archivo:
            comprobado = archivo.read(len(contenido) + 1)
        if comprobado != contenido:
            raise ErrorNegocio("El archivo cambió durante su análisis; no se publicó", 409)
    except Exception:
        ruta.unlink(missing_ok=True)  # únicamente el objeto recién creado sin publicar
        raise
    return clave


def ruta_objeto(clave):
    if not re.fullmatch("[0-9a-f]{32}", clave):
        raise ErrorNegocio("Identificador de almacenamiento inválido", 409)
    ruta = raiz() / clave
    if ruta.is_symlink():
        raise ErrorNegocio("Enlace de almacenamiento no permitido", 409)
    return ruta


def leer(version):
    ruta = ruta_objeto(version.clave)
    try:
        fd = os.open(ruta, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as archivo:
            if not stat.S_ISREG(os.fstat(archivo.fileno()).st_mode):
                raise ErrorNegocio("Objeto de almacenamiento no permitido", 409)
            contenido = archivo.read(min(version.bytes, 50 * 1024 * 1024) + 1)
    except OSError as error:
        raise ErrorNegocio("El archivo no está disponible; revisa su respaldo", 503) from error
    if len(contenido) != version.bytes or hashlib.sha256(contenido).hexdigest() != version.sha256:
        raise ErrorNegocio("Falló la comprobación de integridad del documento", 409)
    return contenido


def previsualizar(version, pagina):
    if not 1 <= pagina <= version.paginas:
        raise ErrorNegocio("Página inexistente", 404)
    return _proceso(leer(version), pagina)
