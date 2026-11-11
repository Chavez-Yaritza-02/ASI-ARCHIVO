"""Proceso de lectura de archivos: sin configuración, credenciales ni conexión a BD.

Recibe bytes por stdin y devuelve metadatos JSON o una página PNG por stdout.
El proceso padre impone tamaño, tiempo y permisos de almacenamiento.
"""

import io
import json
import os
import re
import sys
import warnings

import pymupdf
from PIL import Image, ImageOps

MAX_PIXELES = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELES
warnings.simplefilter("error", Image.DecompressionBombWarning)
ACTIVO = re.compile(
    r"/(?:JavaScript|JS|Launch|EmbeddedFile|RichMedia|OpenAction|AA|XFA|SubmitForm|ImportData|GoToR|URI)\b"
)


def procesar(contenido, pagina=None):
    if contenido.startswith(b"%PDF-"):
        with pymupdf.open(stream=contenido, filetype="pdf") as doc:
            if (
                doc.is_encrypted
                or doc.is_repaired
                or not 1 <= doc.page_count <= 150
                or doc.xref_length() > 20000
            ):
                raise ValueError("PDF cifrado, vacío o demasiado complejo")
            if doc.embfile_count():
                raise ValueError("No se admiten archivos incrustados")
            for xref in range(1, doc.xref_length()):
                objeto = doc.xref_object(xref, compressed=False)
                # Resolver escapes de nombres PDF como /Java#53cript.
                objeto = re.sub(r"#([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)), objeto)
                if ACTIVO.search(objeto):
                    raise ValueError(
                        "El PDF contiene acciones, enlaces externos o contenido activo"
                    )
            for p in doc:
                rect = p.rect
                if (
                    not rect.is_valid
                    or rect.is_infinite
                    or rect.width <= 0
                    or rect.height <= 0
                    or rect.width * rect.height > MAX_PIXELES
                ):
                    raise ValueError("Dimensiones de página no admitidas")
                imagenes = p.get_images(full=True)
                if len(imagenes) > 300 or any(
                    i[2] <= 0 or i[3] <= 0 or max(i[2], i[3]) > 12000 or i[2] * i[3] > MAX_PIXELES
                    for i in imagenes
                ):
                    raise ValueError("Imágenes incrustadas demasiado grandes o complejas")
            if pagina is None:
                return {"mime": "application/pdf", "paginas": doc.page_count}
            if not 1 <= pagina <= doc.page_count:
                raise ValueError("Página inexistente")
            p = doc[pagina - 1]
            escala = min(1.8, 1280 / max(p.rect.width, p.rect.height))
            return p.get_pixmap(matrix=pymupdf.Matrix(escala, escala), alpha=False).tobytes("png")
    with Image.open(io.BytesIO(contenido)) as imagen:
        formato = imagen.format
        if formato not in ("PNG", "JPEG") or getattr(imagen, "n_frames", 1) != 1:
            raise ValueError("Solo se admiten PNG y JPEG estáticos")
        if imagen.width * imagen.height > MAX_PIXELES or max(imagen.size) > 12000:
            raise ValueError("Imagen demasiado grande")
        imagen.verify()
    with Image.open(io.BytesIO(contenido)) as imagen:
        imagen.load()
        if pagina is None:
            return {"mime": "image/png" if formato == "PNG" else "image/jpeg", "paginas": 1}
        if pagina != 1:
            raise ValueError("Página inexistente")
        imagen = ImageOps.exif_transpose(imagen).convert("RGB")
        imagen.thumbnail((1280, 1280))
        salida = io.BytesIO()
        imagen.save(salida, format="PNG")
        return salida.getvalue()


def main(argumentos: list[str] | None = None):
    """`argumentos`: número de página opcional. Desde la aplicación empaquetada (modo
    local) se llama con los argumentos que siguen a `--procesar-archivo`."""
    argumentos = sys.argv[1:] if argumentos is None else argumentos
    # Límite adicional de CPU en los sistemas que lo soportan. Windows usa el timeout del padre.
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        pass
    # En la aplicación de Windows sin consola, sys.stdin/stdout pueden no existir aunque el
    # proceso padre haya conectado tuberías: se usan los descriptores directamente.
    entrada = sys.stdin.buffer if sys.stdin else os.fdopen(0, "rb", closefd=False)
    salida = sys.stdout.buffer if sys.stdout else os.fdopen(1, "wb", closefd=False)
    try:
        contenido = entrada.read(50 * 1024 * 1024 + 1)
        if not contenido or len(contenido) > 50 * 1024 * 1024:
            raise ValueError("Tamaño no permitido")
        resultado = procesar(contenido, int(argumentos[0]) if argumentos else None)
        if not isinstance(resultado, bytes):
            resultado = (json.dumps(resultado) + "\n").encode()
        salida.write(resultado)
        salida.flush()
    except Exception:
        # No devolver detalles del parser o datos del documento al cliente.
        if sys.stderr:
            print("Archivo inválido o no permitido", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
