"""Comunicación con la API. Toda la información pasa por aquí; el cliente
nunca se conecta directamente a la base de datos."""

import os
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import keyring
from keyring.errors import KeyringError

SERVICIO_LLAVERO = "ASI-ARCHIVO"
_HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}


class ErrorApi(Exception):
    """Error mostrable al usuario."""


@dataclass
class UsuarioSesion:
    id: int
    correo: str
    nombre: str
    roles: list[str]
    permisos: list[str]

    def puede(self, permiso: str) -> bool:
        return permiso in self.permisos


def validar_url(url: str) -> str:
    """Solo se permite HTTP sin cifrar contra la propia computadora (desarrollo)."""
    partes = urlparse(url)
    if partes.scheme == "https" or (partes.scheme == "http" and partes.hostname in _HOSTS_LOCALES):
        return url.rstrip("/")
    raise ErrorApi("El servidor debe usar HTTPS")


class ClienteApi:
    def __init__(self, url: str | None = None, transporte: httpx.BaseTransport | None = None):
        url = url or os.environ.get("ASI_SERVIDOR_URL", "http://127.0.0.1:8000")
        self._http = httpx.Client(base_url=validar_url(url), timeout=15, transport=transporte)
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
            self._token = keyring.get_password(SERVICIO_LLAVERO, correo)
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
                keyring.delete_password(SERVICIO_LLAVERO, correo)

    def servidor_disponible(self) -> bool:
        try:
            return self._http.get("/salud").status_code == 200
        except httpx.HTTPError:
            return False

    # --- internos -------------------------------------------------------

    def _cargar_usuario(self) -> UsuarioSesion:
        return UsuarioSesion(**self._peticion("GET", "/auth/yo").json())

    def _guardar_token(self, correo: str) -> None:
        # Si el llavero no está disponible, simplemente no se recuerda la sesión.
        with suppress(KeyringError):
            keyring.set_password(SERVICIO_LLAVERO, correo, self._token or "")

    def _peticion(self, metodo: str, ruta: str, **kwargs) -> httpx.Response:
        encabezados = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            r = self._http.request(metodo, ruta, headers=encabezados, **kwargs)
        except httpx.HTTPError as error:
            raise ErrorApi("No se pudo conectar con el servidor") from error
        if r.status_code >= 400:
            try:
                detalle = r.json().get("detail", r.text)
            except ValueError:
                detalle = r.text
            raise ErrorApi(str(detalle))
        return r
