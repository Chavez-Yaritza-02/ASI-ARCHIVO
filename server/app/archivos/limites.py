"""Límite de petición antes de que multipart pueda acumular una carga ilimitada."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.core.config import obtener_configuracion


class LimiteArchivoMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope.get("path", "").startswith("/documentos")
        ):
            return await self.app(scope, receive, send)
        limite = obtener_configuracion().archivo_max_mb * 1024 * 1024 + 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            longitud = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Longitud inválida"}, status_code=400)(
                scope, receive, send
            )
        if longitud < 0 or longitud > limite:
            return await JSONResponse({"detail": "Carga demasiado grande"}, status_code=413)(
                scope, receive, send
            )
        recibidos = 0

        async def recibir():
            nonlocal recibidos
            mensaje = await receive()
            recibidos += len(mensaje.get("body", b""))
            if recibidos > limite:
                raise HTTPException(413, "Carga demasiado grande")
            return mensaje

        await self.app(scope, recibir, send)
