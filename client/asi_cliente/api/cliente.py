"""Comunicación con la API. Toda la información pasa por aquí; el cliente
nunca se conecta directamente a la base de datos."""

import os
import ssl
import sys
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import keyring
import truststore
from keyring.errors import KeyringError

SERVICIO_LLAVERO = "ASI-ARCHIVO"
_HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}


class ErrorApi(Exception):
    """Error mostrable al usuario. `problemas` trae el detalle (p. ej. cada traslape)."""

    def __init__(self, mensaje: str, problemas: list[str] | None = None, estado: int = 0):
        super().__init__(mensaje)
        self.problemas = problemas or []
        self.estado = estado


@dataclass
class UsuarioSesion:
    id: int
    correo: str
    nombre: str
    roles: list[str]
    permisos: list[str]

    def puede(self, permiso: str) -> bool:
        return permiso in self.permisos


def validar_url(url: str, *, solo_https: bool = False) -> str:
    """Solo se permite HTTP sin cifrar contra la propia computadora (desarrollo)."""
    try:
        partes = urlparse(url.strip())
        puerto = partes.port
        host = partes.hostname
        valido = (
            bool(host)
            and not partes.username
            and not partes.password
            and not partes.query
            and not partes.fragment
            and partes.path in ("", "/")
            and not any(c.isspace() or ord(c) < 32 or c == "\\" for c in url)
        )
    except ValueError:
        valido = False
    if valido and (
        partes.scheme == "https"
        or (not solo_https and partes.scheme == "http" and host in _HOSTS_LOCALES)
    ):
        host = host.encode("idna").decode().lower()
        host = f"[{host}]" if ":" in host else host
        sufijo = (
            f":{puerto}" if puerto and puerto != {"https": 443, "http": 80}[partes.scheme] else ""
        )
        return f"{partes.scheme}://{host}{sufijo}"
    raise ErrorApi("El servidor debe usar HTTPS")


class ClienteApi:
    def __init__(
        self,
        url: str | None = None,
        transporte: httpx.BaseTransport | None = None,
        http: httpx.Client | None = None,
        servicio_llavero: str | None = None,
    ):
        """`http` permite inyectar un cliente ya configurado (las pruebas de integración
        usan el TestClient de FastAPI para hablar con la API real sin abrir un puerto)."""
        if http is None:
            url = url or os.environ.get("ASI_SERVIDOR_URL", "http://127.0.0.1:8000")
            # Escritura amplia: subir un ZIP de horarios por internet puede tardar.
            tiempo = httpx.Timeout(120, connect=8, write=300)
            url = validar_url(url, solo_https=getattr(sys, "frozen", False))
            # Certificados de confianza del sistema operativo: así funciona tanto un
            # certificado público como uno interno instalado por el área de TI en Windows.
            verificacion = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            http = httpx.Client(
                base_url=url,
                timeout=tiempo,
                transport=transporte,
                verify=verificacion,
                trust_env=False,
            )
        self._http = http
        origen = str(http.base_url).rstrip("/")
        self.servicio_llavero = servicio_llavero or (
            f"{SERVICIO_LLAVERO}:{origen}" if origen.startswith("https://") else SERVICIO_LLAVERO
        )
        # Carpeta de datos cuando la aplicación trabaja sola en esta computadora (modo local).
        self.carpeta_local = None
        self._token: str | None = None
        self.usuario: UsuarioSesion | None = None

    # --- sesión ---------------------------------------------------------

    def iniciar_sesion(self, correo: str, contrasena: str, recordar: bool = False) -> UsuarioSesion:
        r = self._peticion("POST", "/auth/login", data={"username": correo, "password": contrasena})
        self._token = r.json()["access_token"]
        self.usuario = self._cargar_usuario()
        if recordar:
            self._guardar_token(correo)
        return self.usuario

    def restaurar_sesion(self, correo: str) -> UsuarioSesion | None:
        """Intenta reutilizar un token guardado en el llavero del sistema."""
        try:
            self._token = keyring.get_password(self.servicio_llavero, correo)
        except KeyringError:
            return None
        if not self._token:
            return None
        try:
            self.usuario = self._cargar_usuario()
        except ErrorApi:
            self.cerrar_sesion(correo)
            return None
        return self.usuario

    def cerrar_sesion(self, correo: str | None = None) -> None:
        self._token = None
        self.usuario = None
        if correo:
            with suppress(KeyringError):
                keyring.delete_password(self.servicio_llavero, correo)

    @property
    def es_local(self) -> bool:
        return self.carpeta_local is not None

    def cambiar_contrasena(self, actual: str, nueva: str) -> None:
        """Cambia la contraseña propia; esta sesión sigue abierta y las demás se cierran."""
        r = self._peticion("POST", "/auth/contrasena", json={"actual": actual, "nueva": nueva})
        self._token = r.json()["access_token"]
        if self.usuario is not None:
            with suppress(KeyringError):
                if keyring.get_password(self.servicio_llavero, self.usuario.correo):
                    self._guardar_token(self.usuario.correo)

    def cerrar(self) -> None:
        self._token = None
        self.usuario = None
        self._http.close()

    @property
    def url(self) -> str:
        return str(self._http.base_url)

    def identidad(self) -> dict:
        """Cómo se presenta el servidor (sin sesión). Vacío si no responde."""
        try:
            r = self._http.get("/sistema/identidad")
            return r.json() if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {}

    def servidor_disponible(self) -> bool:
        try:
            return self._http.get("/salud").status_code == 200
        except httpx.HTTPError:
            return False

    # --- datos -----------------------------------------------------------

    def get(self, ruta: str, **params):
        params = {k: v for k, v in params.items() if v is not None}
        return self._peticion("GET", ruta, params=params).json()

    def post(self, ruta: str, datos: dict | list | None = None):
        return self._peticion("POST", ruta, json=datos if datos is not None else {}).json()

    def put(self, ruta: str, datos: dict | list):
        return self._peticion("PUT", ruta, json=datos).json()

    def patch(self, ruta: str, datos: dict):
        return self._peticion("PATCH", ruta, json=datos).json()

    def subir(self, ruta: str, nombre: str, contenido: bytes, datos: dict):
        """Envía un archivo (multipart), p. ej. un ZIP de horarios."""
        return self._peticion(
            "POST", ruta, files={"archivo": (nombre, contenido)}, data=datos
        ).json()

    def descargar(self, ruta: str, **params) -> bytes:
        return self._peticion("GET", ruta, params=params).content

    def obtener_bytes(self, ruta: str) -> bytes | None:
        try:
            return self._peticion("GET", ruta).content
        except ErrorApi:
            return None

    # --- internos -------------------------------------------------------

    def _cargar_usuario(self) -> UsuarioSesion:
        return UsuarioSesion(**self._peticion("GET", "/auth/yo").json())

    def _guardar_token(self, correo: str) -> None:
        # Si el llavero no está disponible, simplemente no se recuerda la sesión.
        with suppress(KeyringError):
            keyring.set_password(self.servicio_llavero, correo, self._token or "")

    def _peticion(self, metodo: str, ruta: str, **kwargs) -> httpx.Response:
        encabezados = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            r = self._http.request(
                metodo, ruta, headers=encabezados, follow_redirects=False, **kwargs
            )
        except httpx.HTTPError as error:
            raise ErrorApi("No se pudo conectar con el servidor") from error
        if r.is_redirect:
            raise ErrorApi("El servidor redirigió la conexión; verifica su dirección HTTPS")
        if r.status_code >= 400:
            problemas: list[str] = []
            try:
                cuerpo = r.json()
                detalle = cuerpo.get("detail", r.text)
                problemas = cuerpo.get("problemas", [])
            except ValueError:
                detalle = r.text
            if isinstance(detalle, list):  # errores de validación de FastAPI (422)
                problemas = [_error_validacion(e) for e in detalle]
                detalle = "Datos inválidos"
            raise ErrorApi(str(detalle), problemas, r.status_code)
        return r


def _error_validacion(error: dict) -> str:
    campo = ".".join(str(p) for p in error.get("loc", [])[1:])
    mensaje = error.get("msg", "valor inválido").removeprefix("Value error, ")
    return f"{campo}: {mensaje}" if campo else mensaje
