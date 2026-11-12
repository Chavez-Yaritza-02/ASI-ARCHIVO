"""A qué servidor está conectada la aplicación, para mostrarlo siempre en pantalla.

El servidor se describe en `/sistema/identidad`. Los servidores actualizados pueden
declarar su tipo (`tipo_servidor`); con los anteriores se deduce de lo que ya enviaban:
`aceptacion_ficticia` (instancia de demostración/aceptación) y `entorno`.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Servidor:
    tipo: str  # institucional | demostracion | revision | desarrollo | desconocido | local
    titulo: str  # texto corto en mayúsculas, p. ej. «SERVIDOR DE REVISIÓN»
    detalle: str  # qué datos tiene
    direccion: str  # host:puerto

    @property
    def texto(self) -> str:
        if self.tipo == "local":  # no hay dirección de red que mostrar
            return f"{self.titulo} · {self.detalle}"
        return f"{self.titulo} · {self.detalle} · {self.direccion}"


TIPOS = {
    "institucional": ("SERVIDOR INSTITUCIONAL", "datos oficiales"),
    "demostracion": ("SERVIDOR DE DEMOSTRACIÓN", "pruebas, no es el sistema oficial"),
    "revision": ("SERVIDOR DE REVISIÓN", "datos ficticios"),
    "desarrollo": ("SERVIDOR DE DESARROLLO", "no es el sistema oficial"),
    "desconocido": ("SERVIDOR SIN IDENTIFICAR", "confirma con el administrador"),
    "local": ("ESTA COMPUTADORA", "datos guardados en este equipo, sin internet"),
}


def direccion_de(url: str) -> str:
    partes = urlsplit(str(url))
    return partes.netloc or str(url)


def describir_servidor(url: str, identidad: dict | None) -> Servidor:
    identidad = identidad or {}
    tipo = identidad.get("tipo_servidor")
    if tipo not in TIPOS:
        if identidad.get("aceptacion_ficticia"):
            tipo = "demostracion"
        elif identidad.get("entorno") == "produccion":
            tipo = "institucional"
        elif identidad.get("entorno"):
            tipo = "desarrollo"
        else:
            tipo = "desconocido"
    titulo, detalle = TIPOS[tipo]
    return Servidor(tipo, titulo, detalle, direccion_de(url))
