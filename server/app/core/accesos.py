"""Log operativo sin tokens, cuerpos, correos ni parámetros de búsqueda."""

import logging
import uuid

log = logging.getLogger("asi.accesos")


async def registrar_acceso(request, call_next):
    id_ = uuid.uuid4().hex
    response = await call_next(request)
    ruta = getattr(request.scope.get("route"), "path", "ruta-no-encontrada")
    log.info(
        "solicitud=%s metodo=%s ruta=%s estado=%s", id_, request.method, ruta, response.status_code
    )
    response.headers["X-Request-ID"] = id_
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path != "/salud":
        response.headers["Cache-Control"] = "no-store"
    return response
