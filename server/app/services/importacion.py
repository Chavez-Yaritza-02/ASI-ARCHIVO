"""Importación de horarios desde PDF: carga, OCR, revisión y aprobación.

Flujo:
1. iniciar(): recibe un ZIP o PDF, valida límites, detecta archivos ya importados y
   deja la importación "procesando".
2. procesar(): (en segundo plano) OCR de cada PDF; guarda cada página como propuesta
   "por revisar", con lo leído y lo que coincidió con los catálogos.
3. guardar_revision() / aceptar_sugerencias(): el usuario corrige y confirma.
4. aprobar(): solo si no queda nada pendiente, crea un horario en *borrador*.
   Confirmarlo como vigente es un paso aparte (permiso horarios.confirmar).

El archivo original no se modifica ni se guarda: solo su huella SHA-256 (para detectar
duplicados) y el recorte de imagen de cada celda (como evidencia para la revisión).
"""

import contextlib
import hashlib
import io
import logging
import os
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers import coincidencias as co
from app.importers.analisis import DIAS
from app.models import (
    Asignatura,
    Aula,
    CeldaImportada,
    Docente,
    DocumentoImportado,
    Grupo,
    Horario,
    Importacion,
    PaginaImportada,
    Periodo,
    Usuario,
)
from app.services import horarios as servicio_horarios
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, normalizar

log = logging.getLogger(__name__)

TAMANO_MAXIMO = 60 * 1024 * 1024  # archivo subido
TAMANO_MAXIMO_DESCOMPRIMIDO = 300 * 1024 * 1024  # contenido total del ZIP
MAXIMO_PDFS = 300
ESTADOS_RESUELTOS = (co.COINCIDE, "confirmado")
TITULOS_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]


# --- Lectura del archivo ----------------------------------------------------------


def extraer_pdfs(nombre: str, contenido: bytes) -> list[tuple[str, bytes]]:
    """Devuelve [(nombre, contenido)] de los PDF del archivo (ZIP o PDF suelto)."""
    if len(contenido) > TAMANO_MAXIMO:
        raise ErrorNegocio("El archivo supera el tamaño máximo (60 MB)", 413)
    if contenido.startswith(b"%PDF"):
        return [(PurePosixPath(nombre).name, contenido)]
    if not zipfile.is_zipfile(io.BytesIO(contenido)):
        raise ErrorNegocio("El archivo debe ser un PDF o un ZIP con PDFs", 415)

    pdfs: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
        entradas = [e for e in zf.infolist() if not e.is_dir()]
        if sum(e.file_size for e in entradas) > TAMANO_MAXIMO_DESCOMPRIMIDO:
            raise ErrorNegocio("El ZIP es demasiado grande al descomprimirlo", 413)
        for entrada in entradas:
            nombre_entrada = entrada.filename
            if not entrada.flag_bits & 0x800:  # nombres sin marca UTF-8 (p. ej. con "Ñ")
                with contextlib.suppress(UnicodeError):
                    nombre_entrada = nombre_entrada.encode("cp437").decode("utf-8")
            # Solo el nombre, nunca la ruta: evita escribir fuera de lugar ("../").
            base = PurePosixPath(nombre_entrada.replace("\\", "/")).name
            if not base.lower().endswith(".pdf") or base.startswith("."):
                continue
            datos = zf.read(entrada)
            if datos.startswith(b"%PDF"):
                pdfs.append((base, datos))
    if not pdfs:
        raise ErrorNegocio("El archivo no contiene PDFs", 422)
    if len(pdfs) > MAXIMO_PDFS:
        raise ErrorNegocio(f"El ZIP contiene más de {MAXIMO_PDFS} PDFs", 413)
    return sorted(pdfs)


def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


# --- Inicio y procesamiento ----------------------------------------------------------


def iniciar(
    sesion: Session, usuario: Usuario, periodo_id: int, nombre: str, contenido: bytes
) -> tuple[Importacion, list[tuple[int, bytes]]]:
    """Registra la importación y devuelve los PDFs pendientes de OCR: [(documento_id, datos)]."""
    periodo = sesion.get(Periodo, periodo_id)
    if periodo is None:
        raise NoEncontrado("El periodo")
    if periodo.estado == "cerrado":
        raise ErrorNegocio(f"El periodo {periodo.nombre} está cerrado", 409)
    pdfs = extraer_pdfs(nombre, contenido)

    importacion = Importacion(
        periodo_id=periodo_id,
        usuario_id=usuario.id,
        nombre_archivo=PurePosixPath(nombre).name[:255],
        sha256=_sha256(contenido),
        estado="procesando",
        total_documentos=len(pdfs),
    )
    sesion.add(importacion)
    sesion.flush()

    trabajos: list[tuple[int, bytes]] = []
    vistos: dict[str, DocumentoImportado] = {}
    for nombre_pdf, datos in pdfs:
        huella = _sha256(datos)
        documento = DocumentoImportado(
            importacion_id=importacion.id, nombre_archivo=nombre_pdf[:255], sha256=huella
        )
        anterior = vistos.get(huella) or sesion.scalar(
            select(DocumentoImportado)
            .join(Importacion)
            .where(
                DocumentoImportado.sha256 == huella,
                DocumentoImportado.estado == "procesado",
                Importacion.estado != "cancelada",
                Importacion.id != importacion.id,
            )
            .limit(1)
        )
        if anterior is not None:
            documento.estado = "duplicado"
            documento.mensaje = (
                f"Idéntico a {anterior.nombre_archivo} (importación {anterior.importacion_id})"
            )
        sesion.add(documento)
        sesion.flush()
        if anterior is not None:
            documento.duplicado_de_id = anterior.id
        else:
            vistos[huella] = documento
            trabajos.append((documento.id, datos))
    importacion.procesados = len(pdfs) - len(trabajos)
    auditar(
        sesion,
        usuario,
        "importar",
        "importacion",
        importacion.id,
        despues={
            "archivo": importacion.nombre_archivo,
            "sha256": importacion.sha256,
            "pdfs": len(pdfs),
            "duplicados": len(pdfs) - len(trabajos),
            "periodo_id": periodo_id,
        },
    )
    sesion.commit()
    return importacion, trabajos


def ocr_documento(datos: bytes) -> list[dict] | str:
    """OCR de un PDF completo (se ejecuta en otro proceso para no bloquear la API).

    Si el PDF no se puede leer devuelve el tipo de error, para marcar solo ese documento.
    """
    from app.importers.ocr import paginas_de_pdf, procesar_pagina

    try:
        return [procesar_pagina(img, con_imagenes=True) for img in paginas_de_pdf(datos)]
    except Exception as error:  # PDF dañado o ilegible
        return error.__class__.__name__


def _procesos() -> int:
    return max(1, int(os.environ.get("ASI_OCR_PROCESOS", os.cpu_count() or 1)))


def procesar(sesion: Session, importacion_id: int, trabajos: list[tuple[int, bytes]]) -> None:
    """OCR de los PDFs y registro de las propuestas. Pensado para correr en segundo plano."""
    importacion = sesion.get(Importacion, importacion_id)
    try:
        catalogos = _cargar_catalogos(sesion)
        if _procesos() == 1 or len(trabajos) <= 1:
            resultados = (ocr_documento(datos) for _, datos in trabajos)
            _registrar(sesion, importacion, trabajos, resultados, catalogos)
        else:
            with ProcessPoolExecutor(max_workers=_procesos()) as pool:
                resultados = pool.map(ocr_documento, [datos for _, datos in trabajos])
                _registrar(sesion, importacion, trabajos, resultados, catalogos)
        importacion.estado = "en_revision"
        _marcar_duplicados(sesion, importacion)
    except Exception as error:  # el detalle queda en el registro del servidor
        log.exception("Falló la importación %s", importacion_id)
        sesion.rollback()
        importacion = sesion.get(Importacion, importacion_id)
        importacion.estado = "error"
        importacion.mensaje = f"Error al procesar: {error.__class__.__name__}"
    sesion.commit()


def _registrar(sesion, importacion, trabajos, resultados, catalogos) -> None:
    for (documento_id, _), paginas in zip(trabajos, resultados, strict=True):
        documento = sesion.get(DocumentoImportado, documento_id)
        if isinstance(paginas, str):
            documento.estado = "error"
            documento.mensaje = f"No se pudo leer el PDF ({paginas})"
            importacion.procesados += 1
            sesion.commit()
            continue
        documento.paginas_total = len(paginas)
        for numero, datos in enumerate(paginas, 1):
            documento.paginas.append(_crear_pagina(numero, datos, catalogos))
        importacion.procesados += 1
        sesion.commit()  # progreso visible para el cliente


@dataclass
class _Catalogos:
    aulas: list[tuple[int, str]]
    asignaturas: list[tuple[int, str]]
    docentes: list[tuple[int, str, str | None]]


def _cargar_catalogos(sesion: Session) -> _Catalogos:
    return _Catalogos(
        aulas=[(a.id, a.clave) for a in sesion.scalars(select(Aula).where(Aula.activo))],
        asignaturas=[
            (a.id, a.nombre) for a in sesion.scalars(select(Asignatura).where(Asignatura.activo))
        ],
        docentes=[
            (d.id, d.nombre, d.nomina)
            for d in sesion.scalars(select(Docente).where(Docente.activo))
        ],
    )


def _fecha(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def _crear_pagina(numero: int, datos: dict, catalogos: _Catalogos) -> PaginaImportada:
    qr = datos.get("qr") or {}
    pagina = PaginaImportada(
        numero=numero,
        estado="error" if datos.get("error") else "por_revisar",
        mensaje=datos.get("error") or "",
        encabezado=qr or None,
        qr_texto=datos.get("qr_texto") if qr else None,
        docente_texto=(qr.get("docente") or datos.get("docente_ocr") or "")[:150],
        nomina=qr.get("nomina"),
        periodo_texto=qr.get("periodo"),
        version_documento=qr.get("version"),
        fecha_documento=_fecha(qr.get("fecha")),
        horas_qr=(qr.get("horas") or {}).get("TOT"),
    )
    r = co.buscar_docente(pagina.docente_texto, pagina.nomina, catalogos.docentes)
    pagina.docente_id, pagina.docente_estado = r.id, r.estado

    for clave, celda in (datos.get("celdas") or {}).items():
        dia, hora = clave.rsplit("-", 1)
        asignatura = co.buscar_asignatura(celda.get("actividad") or "", catalogos.asignaturas)
        aula = co.buscar_aula(celda.get("aula"), catalogos.aulas)
        letra = letra_de_grupo(celda.get("grupo"))
        pagina.celdas.append(
            CeldaImportada(
                dia=DIAS.index(dia),
                hora=int(hora),
                origen="ocr",
                texto_ocr=celda.get("texto", ""),
                actividad_texto=(celda.get("actividad") or "")[:150],
                grupo_texto=letra,
                aula_texto=(celda.get("aula") or None) and celda["aula"][:40],
                imagen_png=celda.get("imagen_png"),
                asignatura_id=asignatura.id,
                asignatura_estado=asignatura.estado,
                aula_id=aula.id,
                aula_estado=aula.estado,
                # La letra sola no identifica al grupo: queda pendiente de validación.
                grupo_letra=letra,
                grupo_estado="pendiente" if letra else co.VACIO,
            )
        )
    return pagina


# Los grupos son letras: el OCR a veces las lee como dígitos parecidos ("O" -> "0").
_DIGITO_A_LETRA = str.maketrans("0815", "OBIS")


def letra_de_grupo(texto: str | None) -> str | None:
    letra = (texto or "").strip().upper()[:5]
    return letra.translate(_DIGITO_A_LETRA) or None


def _marcar_duplicados(sesion: Session, importacion: Importacion) -> None:
    """Páginas con el mismo QR (mismo docente, versión y fecha) son copias de la primera."""
    primeras: dict[str, PaginaImportada] = {}
    for documento in importacion.documentos:
        for pagina in documento.paginas:
            if not pagina.qr_texto or pagina.estado != "por_revisar":
                continue
            original = primeras.setdefault(pagina.qr_texto, pagina)
            if original is not pagina:
                sesion.flush()
                pagina.estado = "duplicada"
                pagina.duplicado_de_id = original.id
                pagina.mensaje = (
                    f"Copia de {original.documento.nombre_archivo}, página {original.numero}"
                )


# --- Consulta ----------------------------------------------------------------------------


def obtener(sesion: Session, id_: int) -> Importacion:
    importacion = sesion.get(Importacion, id_)
    if importacion is None:
        raise NoEncontrado("La importación")
    return importacion


def listar(sesion: Session) -> list[Importacion]:
    return list(sesion.scalars(select(Importacion).order_by(Importacion.id.desc())))


def obtener_pagina(sesion: Session, id_: int) -> PaginaImportada:
    pagina = sesion.get(PaginaImportada, id_)
    if pagina is None:
        raise NoEncontrado("La página")
    return pagina


def obtener_celda(sesion: Session, id_: int) -> CeldaImportada:
    celda = sesion.get(CeldaImportada, id_)
    if celda is None:
        raise NoEncontrado("La celda")
    return celda


def _posicion(c: CeldaImportada) -> str:
    return f"{TITULOS_DIAS[c.dia]} {c.hora:02d}:00"


def pendientes(sesion: Session, pagina: PaginaImportada) -> list[str]:
    """Lo que impide aprobar la página. Vacío = lista para aprobar."""
    problemas: list[str] = []
    if pagina.docente_id is None:
        problemas.append("Elige el docente")
    elif pagina.docente_estado not in ESTADOS_RESUELTOS:
        problemas.append("Confirma el docente sugerido")
    if not pagina.celdas:
        problemas.append("La página no tiene actividades")
    for c in pagina.celdas:
        if c.asignatura_id is None:
            problemas.append(f"{_posicion(c)}: elige la asignatura («{c.actividad_texto}»)")
        elif c.asignatura_estado not in ESTADOS_RESUELTOS:
            problemas.append(f"{_posicion(c)}: confirma la asignatura sugerida")
        if c.aula_estado == co.SUGERIDO:
            problemas.append(f"{_posicion(c)}: confirma el aula sugerida («{c.aula_texto}»)")
        elif c.aula_estado == co.SIN_COINCIDENCIA:
            problemas.append(f"{_posicion(c)}: elige el aula («{c.aula_texto}»)")
        if c.asignatura_id is not None and c.grupo_id is None and not c.grupo_letra:
            asignatura = sesion.get(Asignatura, c.asignatura_id)
            if asignatura is not None and asignatura.tipo == "materia":
                problemas.append(f"{_posicion(c)}: la materia necesita grupo")
    return problemas


def _horario_existente(sesion: Session, pagina: PaginaImportada) -> Horario | None:
    if pagina.docente_id is None or pagina.fecha_documento is None:
        return None
    return sesion.scalar(
        select(Horario).where(
            Horario.docente_id == pagina.docente_id,
            Horario.periodo_id == pagina.documento.importacion.periodo_id,
            Horario.version_documento == pagina.version_documento,
            Horario.fecha_documento == pagina.fecha_documento,
            Horario.estado != "descartado",
        )
    )


def avisos(sesion: Session, pagina: PaginaImportada) -> list[str]:
    """Situaciones a revisar que no impiden aprobar (algunas piden confirmación)."""
    lista: list[str] = []
    if not pagina.qr_texto:
        lista.append("No se pudo leer el código QR: el encabezado salió del OCR; verifícalo")
    periodo = sesion.get(Periodo, pagina.documento.importacion.periodo_id)
    if pagina.periodo_texto and normalizar(pagina.periodo_texto) != normalizar(periodo.nombre):
        lista.append(
            f"El documento dice «{pagina.periodo_texto}», pero se importa en {periodo.nombre}"
        )
    if pagina.horas_qr is not None and pagina.horas_qr != len(pagina.celdas):
        lista.append(
            f"El documento indica {pagina.horas_qr} h y hay {len(pagina.celdas)} celdas: "
            "puede faltar o sobrar alguna"
        )
    letras = sum(1 for c in pagina.celdas if c.grupo_id is None and c.grupo_letra)
    if letras:
        lista.append(
            f"{letras} celda(s) con grupo pendiente de validación (solo se conoce la letra)"
        )
    if pagina.docente_id is not None:
        # Choques con horarios vigentes de otros docentes, antes de aprobar.
        lista += servicio_horarios.choques(
            sesion, periodo.id, pagina.docente_id, _a_bloques(pagina)
        )
    existente = _horario_existente(sesion, pagina)
    if existente is not None:
        lista.append(
            f"Este documento ya se importó: horario versión {existente.version} "
            f"({existente.estado})"
        )
    versiones = {
        p.version_documento
        for p in pagina.documento.paginas
        if p.version_documento is not None and p.estado != "duplicada"
    }
    if len(versiones) > 1:
        lista.append(
            "Este PDF contiene varias versiones del horario ("
            + ", ".join(f"v{v}" for v in sorted(versiones))
            + "): aprueba la que corresponda"
        )
    return lista


# --- Revisión -----------------------------------------------------------------------------


def _exigir_por_revisar(pagina: PaginaImportada) -> None:
    if pagina.estado != "por_revisar":
        raise ErrorNegocio(f"La página está {pagina.estado.replace('_', ' ')}", 409)


@dataclass
class CeldaRevisada:
    dia: int
    hora: int
    asignatura_id: int | None
    aula_id: int | None = None
    grupo_id: int | None = None
    grupo_letra: str | None = None
    id: int | None = None  # celda leída por el OCR que se conserva (con su imagen)
    confirmar: bool = False  # el usuario revisó la celda y acepta los valores mostrados


def _validar_catalogo(sesion: Session, modelo, id_: int | None, que: str) -> None:
    if id_ is None:
        return
    obj = sesion.get(modelo, id_)
    if obj is None or not obj.activo:
        raise ErrorNegocio(f"{que} {id_} no existe o está inactiva", 422)


def guardar_revision(
    sesion: Session,
    usuario: Usuario,
    pagina_id: int,
    docente_id: int | None,
    celdas: list[CeldaRevisada] | None,
) -> PaginaImportada:
    """Guarda las correcciones del usuario. Todo valor elegido o cambiado queda confirmado."""
    pagina = obtener_pagina(sesion, pagina_id)
    _exigir_por_revisar(pagina)
    cambios: dict = {}

    if docente_id is not None and docente_id != pagina.docente_id:
        _validar_catalogo(sesion, Docente, docente_id, "El docente")
        cambios["docente"] = {"antes": pagina.docente_id, "despues": docente_id}
        pagina.docente_id = docente_id
        pagina.docente_estado = "confirmado"

    if celdas is not None:
        posiciones = [(c.dia, c.hora) for c in celdas]
        if len(set(posiciones)) != len(posiciones):
            raise ErrorNegocio("Hay dos actividades en la misma hora", 422)
        existentes = {c.id: c for c in pagina.celdas}
        conservar: list[CeldaImportada] = []
        for nueva in celdas:
            if not (0 <= nueva.dia <= 5 and 7 <= nueva.hora <= 22):
                raise ErrorNegocio(f"Posición inválida: día {nueva.dia}, hora {nueva.hora}", 422)
            _validar_catalogo(sesion, Asignatura, nueva.asignatura_id, "La asignatura")
            _validar_catalogo(sesion, Aula, nueva.aula_id, "El aula")
            _validar_catalogo(sesion, Grupo, nueva.grupo_id, "El grupo")
            celda = existentes.pop(nueva.id, None) if nueva.id is not None else None
            if celda is None:
                celda = CeldaImportada(
                    origen="manual", asignatura_estado="confirmado", aula_estado="confirmado"
                )
            if celda.asignatura_id != nueva.asignatura_id:
                celda.asignatura_id = nueva.asignatura_id
                celda.asignatura_estado = (
                    "confirmado" if nueva.asignatura_id else (co.SIN_COINCIDENCIA)
                )
            if celda.aula_id != nueva.aula_id:
                celda.aula_id = nueva.aula_id
                celda.aula_estado = "confirmado"  # también si el usuario la dejó sin aula
            letra = (nueva.grupo_letra or "").strip().upper()[:5] or None
            celda.grupo_id = nueva.grupo_id
            celda.grupo_letra = None if nueva.grupo_id else letra
            celda.grupo_estado = (
                "confirmado" if nueva.grupo_id else ("pendiente" if letra else co.VACIO)
            )
            if nueva.confirmar:
                if celda.asignatura_id:
                    celda.asignatura_estado = "confirmado"
                if celda.aula_id or celda.aula_estado != co.VACIO:
                    celda.aula_estado = "confirmado"
            celda.dia, celda.hora = nueva.dia, nueva.hora
            conservar.append(celda)
        # Evita choques con la restricción de posición única al mover celdas.
        for eliminada in existentes.values():
            pagina.celdas.remove(eliminada)
        sesion.flush()
        pagina.celdas = conservar
        cambios["celdas"] = len(conservar)

    if cambios:
        auditar(sesion, usuario, "revisar", "importacion_pagina", pagina.id, despues=cambios)
    sesion.commit()
    sesion.refresh(pagina)
    return pagina


def aceptar_sugerencias(sesion: Session, usuario: Usuario, pagina_id: int) -> PaginaImportada:
    """Acepta todas las sugerencias de la página (docente, asignaturas y aulas)."""
    pagina = obtener_pagina(sesion, pagina_id)
    _exigir_por_revisar(pagina)
    aceptadas = 0
    if pagina.docente_estado == co.SUGERIDO and pagina.docente_id:
        pagina.docente_estado = "confirmado"
        aceptadas += 1
    for c in pagina.celdas:
        if c.asignatura_estado == co.SUGERIDO and c.asignatura_id:
            c.asignatura_estado = "confirmado"
            aceptadas += 1
        if c.aula_estado == co.SUGERIDO and c.aula_id:
            c.aula_estado = "confirmado"
            aceptadas += 1
    if aceptadas:
        auditar(
            sesion,
            usuario,
            "aceptar_sugerencias",
            "importacion_pagina",
            pagina.id,
            despues={"aceptadas": aceptadas},
        )
    sesion.commit()
    return pagina


def _a_bloques(pagina: PaginaImportada) -> list[servicio_horarios.BloqueEntrada]:
    """Une horas consecutivas idénticas del mismo día en bloques."""
    bloques: list[servicio_horarios.BloqueEntrada] = []
    for c in sorted(pagina.celdas, key=lambda c: (c.dia, c.hora)):
        clave = (c.asignatura_id, c.grupo_id, c.grupo_letra, c.aula_id)
        ultimo = bloques[-1] if bloques else None
        if (
            ultimo
            and ultimo.dia == c.dia
            and ultimo.hora_fin == time(c.hora)
            and (ultimo.asignatura_id, ultimo.grupo_id, ultimo.grupo_letra, ultimo.aula_id) == clave
        ):
            bloques[-1] = servicio_horarios.BloqueEntrada(
                ultimo.dia,
                ultimo.hora_inicio,
                time(c.hora + 1),
                c.asignatura_id,
                c.grupo_id,
                c.aula_id,
                c.grupo_letra,
            )
        else:
            bloques.append(
                servicio_horarios.BloqueEntrada(
                    c.dia,
                    time(c.hora),
                    time(c.hora + 1),
                    c.asignatura_id,
                    c.grupo_id,
                    c.aula_id,
                    c.grupo_letra,
                )
            )
    return bloques


def aprobar(
    sesion: Session,
    usuario: Usuario,
    pagina_id: int,
    aceptar_diferencia_horas: bool = False,
    permitir_duplicado: bool = False,
) -> Horario:
    """Crea un horario en borrador con lo revisado. No lo vuelve vigente."""
    pagina = obtener_pagina(sesion, pagina_id)
    _exigir_por_revisar(pagina)
    faltan = pendientes(sesion, pagina)
    if faltan:
        raise ErrorNegocio("La revisión no está completa", 422, faltan)
    if (
        pagina.horas_qr is not None
        and pagina.horas_qr != len(pagina.celdas)
        and not aceptar_diferencia_horas
    ):
        raise ErrorNegocio(
            "El número de horas no coincide con el documento",
            409,
            [f"Documento: {pagina.horas_qr} h; revisado: {len(pagina.celdas)} h"],
        )
    existente = _horario_existente(sesion, pagina)
    if existente is not None and not permitir_duplicado:
        raise ErrorNegocio(
            "Este documento ya se importó",
            409,
            [f"Horario versión {existente.version} ({existente.estado})"],
        )

    importacion = pagina.documento.importacion
    horario = servicio_horarios.crear_borrador(
        sesion,
        usuario,
        pagina.docente_id,
        importacion.periodo_id,
        origen="pdf",
        notas=f"Importado de {pagina.documento.nombre_archivo}, página {pagina.numero} "
        f"(importación {importacion.id})",
    )
    horario.fecha_documento = pagina.fecha_documento
    horario.version_documento = pagina.version_documento
    horario = servicio_horarios.reemplazar_bloques(sesion, usuario, horario.id, _a_bloques(pagina))

    pagina.estado = "aprobada"
    pagina.horario_id = horario.id
    pagina.revisado_por_id = usuario.id
    pagina.revisado_en = datetime.now(UTC)
    auditar(
        sesion,
        usuario,
        "aprobar",
        "importacion_pagina",
        pagina.id,
        despues={"horario_id": horario.id, "docente_id": pagina.docente_id},
    )
    _actualizar_estado(importacion)
    sesion.commit()
    return horario


def descartar(sesion: Session, usuario: Usuario, pagina_id: int) -> PaginaImportada:
    pagina = obtener_pagina(sesion, pagina_id)
    if pagina.estado == "aprobada":
        raise ErrorNegocio("La página ya se aprobó; descarta el horario borrador creado", 409)
    pagina.estado = "descartada"
    auditar(sesion, usuario, "descartar", "importacion_pagina", pagina.id)
    _actualizar_estado(pagina.documento.importacion)
    sesion.commit()
    return pagina


def restaurar(sesion: Session, usuario: Usuario, pagina_id: int) -> PaginaImportada:
    """Devuelve a revisión una página descartada o marcada como duplicada."""
    pagina = obtener_pagina(sesion, pagina_id)
    if pagina.estado not in ("descartada", "duplicada"):
        raise ErrorNegocio("Solo se restauran páginas descartadas o duplicadas", 409)
    if pagina.documento.importacion.estado == "cancelada":
        raise ErrorNegocio("La importación está cancelada", 409)
    pagina.estado = "por_revisar"
    pagina.documento.importacion.estado = "en_revision"
    auditar(sesion, usuario, "restaurar", "importacion_pagina", pagina.id)
    sesion.commit()
    return pagina


def cancelar(sesion: Session, usuario: Usuario, importacion_id: int) -> Importacion:
    importacion = obtener(sesion, importacion_id)
    if importacion.estado == "procesando":
        raise ErrorNegocio("Espera a que termine el procesamiento", 409)
    for documento in importacion.documentos:
        for pagina in documento.paginas:
            if pagina.estado == "por_revisar":
                pagina.estado = "descartada"
    importacion.estado = "cancelada"
    auditar(sesion, usuario, "cancelar", "importacion", importacion.id)
    sesion.commit()
    return importacion


def _actualizar_estado(importacion: Importacion) -> None:
    abiertas = any(p.estado == "por_revisar" for d in importacion.documentos for p in d.paginas)
    if importacion.estado == "en_revision" and not abiertas:
        importacion.estado = "terminada"
