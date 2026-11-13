"""Metadatos, versiones, vínculos y accesos auditados del archivo digital."""

from sqlalchemy import func, select

from app.archivos import almacen
from app.models import (
    AsistenciaHora,
    CategoriaDocumento,
    Docente,
    Documento,
    DocumentoAsistencia,
    Periodo,
    VersionDocumento,
)
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, hoy, instantanea, normalizar
from asi_shared import Permiso

CAMPOS = ["nombre", "descripcion", "fecha", "categoria_id", "docente_id", "periodo_id", "activo"]


def obtener(sesion, id_, bloquear=False):
    q = select(Documento).where(Documento.id == id_)
    if bloquear:
        q = q.with_for_update(of=Documento)
    d = sesion.scalar(q)
    if d is None:
        raise NoEncontrado("El documento")
    return d


def categoria(sesion, id_):
    c = sesion.get(CategoriaDocumento, id_)
    if c is None:
        raise NoEncontrado("La categoría")
    return c


def validar_metadatos(sesion, datos):
    if not (datos["nombre"] or "").strip():
        raise ErrorNegocio("Indica el nombre del documento", 422)
    categoria(sesion, datos["categoria_id"])
    for campo, modelo in (("docente_id", Docente), ("periodo_id", Periodo)):
        if datos.get(campo) is not None and sesion.get(modelo, datos[campo]) is None:
            raise NoEncontrado("La referencia del documento")


def version(sesion, documento_id, version_id=None):
    q = select(VersionDocumento).where(VersionDocumento.documento_id == documento_id)
    if version_id is not None:
        q = q.where(VersionDocumento.id == version_id)
    v = sesion.scalar(q.order_by(VersionDocumento.numero.desc()))
    if v is None:
        raise NoEncontrado("La versión del documento")
    return v


def version_salida(v):
    return {
        "id": v.id,
        "numero": v.numero,
        "nombre_original": v.nombre_original,
        "mime": v.mime,
        "sha256": v.sha256,
        "bytes": v.bytes,
        "paginas": v.paginas,
        "motivo": v.motivo,
        "subido_por_id": v.subido_por_id,
        "creado_en": v.creado_en,
    }


def resumen(sesion, d):
    docente = sesion.get(Docente, d.docente_id) if d.docente_id else None
    periodo = sesion.get(Periodo, d.periodo_id) if d.periodo_id else None
    return {
        "id": d.id,
        **instantanea(d, CAMPOS),
        "categoria": d.categoria.nombre,
        "categoria_clave": d.categoria.clave,
        "admite_justificantes": d.categoria.admite_justificantes,
        "docente": docente.nombre if docente else None,
        "periodo": periodo.nombre if periodo else None,
        "version_actual": version_salida(version(sesion, d.id)),
    }


def listar(
    sesion,
    usuario,
    texto="",
    docente_id=None,
    periodo_id=None,
    categoria_id=None,
    desde=None,
    hasta=None,
    incluir_archivados=False,
    offset=0,
    limite=50,
    docente_nombre="",
    asistencia_id=None,
):
    if desde and hasta and hasta < desde:
        raise ErrorNegocio("La fecha final no puede ser anterior a la inicial", 422)
    q = select(Documento)
    if docente_nombre:
        q = q.where(
            Documento.docente_id.in_(
                select(Docente.id).where(
                    Docente.nombre_normalizado.contains(normalizar(docente_nombre), autoescape=True)
                )
            )
        )
    if asistencia_id is not None:
        q = q.where(
            Documento.id.in_(
                select(VersionDocumento.documento_id)
                .join(DocumentoAsistencia)
                .where(
                    DocumentoAsistencia.asistencia_id == asistencia_id,
                    DocumentoAsistencia.activo.is_(True),
                )
            )
        )
    if texto:
        q = q.where(Documento.nombre_normalizado.contains(normalizar(texto), autoescape=True))
    for campo, valor in (
        (Documento.docente_id, docente_id),
        (Documento.periodo_id, periodo_id),
        (Documento.categoria_id, categoria_id),
    ):
        if valor is not None:
            q = q.where(campo == valor)
    if desde:
        q = q.where(Documento.fecha >= desde)
    if hasta:
        q = q.where(Documento.fecha <= hasta)
    if not incluir_archivados:
        q = q.where(Documento.activo.is_(True))
    total = sesion.scalar(select(func.count()).select_from(q.subquery()))
    docs = list(
        sesion.scalars(
            q.order_by(Documento.fecha.desc(), Documento.id.desc()).offset(offset).limit(limite)
        )
    )
    salida = [resumen(sesion, d) for d in docs]
    auditar(
        sesion,
        usuario,
        "buscar",
        "documento",
        None,
        despues={
            "ids": [d.id for d in docs],
            "texto": texto,
            "docente_id": docente_id,
            "periodo_id": periodo_id,
            "categoria_id": categoria_id,
            "docente_nombre": docente_nombre,
            "desde": desde.isoformat() if desde else None,
            "hasta": hasta.isoformat() if hasta else None,
            "incluir_archivados": incluir_archivados,
            "asistencia_id": asistencia_id,
            "offset": offset,
            "limite": limite,
        },
    )
    sesion.commit()
    return {"total": total, "resultados": salida}


def detalle(sesion, usuario, id_):
    d = obtener(sesion, id_)
    salida = resumen(sesion, d)
    salida["versiones"] = [
        version_salida(v)
        for v in sesion.scalars(
            select(VersionDocumento)
            .where(VersionDocumento.documento_id == d.id)
            .order_by(VersionDocumento.numero.desc())
        )
    ]
    salida["asistencias"] = []
    if Permiso.ASISTENCIA_VER in usuario.permisos:
        salida["asistencias"] = [
            {
                "id": vinculo.id,
                "asistencia_id": vinculo.asistencia_id,
                "version_id": vinculo.version_id,
                "activo": vinculo.activo,
            }
            for vinculo in sesion.scalars(
                select(DocumentoAsistencia)
                .join(VersionDocumento)
                .where(VersionDocumento.documento_id == d.id)
                .order_by(DocumentoAsistencia.id)
            )
        ]
    auditar(sesion, usuario, "consultar", "documento", d.id)
    sesion.commit()
    return salida


def _nueva_version(sesion, usuario, d, contenido, nombre, mime, motivo):
    if len(motivo.strip()) < 5:
        raise ErrorNegocio("Indica el motivo de la nueva versión", 422)
    datos = almacen.validar(contenido, nombre, mime)
    anterior = sesion.scalar(
        select(VersionDocumento)
        .where(VersionDocumento.documento_id == d.id)
        .order_by(VersionDocumento.numero.desc())
    )
    if anterior and anterior.sha256 == datos["sha256"]:
        raise ErrorNegocio("El contenido es idéntico a la versión actual", 409)
    clave = almacen.guardar(contenido)
    try:
        v = VersionDocumento(
            documento_id=d.id,
            numero=anterior.numero + 1 if anterior else 1,
            clave=clave,
            motivo=motivo.strip(),
            subido_por_id=usuario.id,
            **datos,
        )
        sesion.add(v)
        sesion.flush()
        auditar(
            sesion,
            usuario,
            "subir_version" if anterior else "subir",
            "documento",
            d.id,
            despues={
                "version_id": v.id,
                "numero": v.numero,
                "sha256": v.sha256,
                "bytes": v.bytes,
                "motivo": v.motivo,
            },
        )
        salida = {"documento_id": d.id, "version": version_salida(v)}
    except Exception:
        sesion.rollback()
        almacen.ruta_objeto(clave).unlink(missing_ok=True)  # solo la nueva carga fallida
        raise
    # Una desconexión al confirmar puede dejar resultado incierto: conservar el objeto
    # permite reconciliarlo, en vez de borrar un original cuya fila sí pudo confirmarse.
    sesion.commit()
    return salida


def crear(sesion, usuario, datos, contenido, nombre, mime):
    validar_metadatos(sesion, datos)
    d = Documento(**datos, nombre_normalizado=normalizar(datos["nombre"]), creado_por_id=usuario.id)
    d.nombre = d.nombre.strip()
    sesion.add(d)
    sesion.flush()
    auditar(sesion, usuario, "crear", "documento", d.id, despues=instantanea(d, CAMPOS))
    return _nueva_version(sesion, usuario, d, contenido, nombre, mime, "Carga inicial")


def subir_version(sesion, usuario, id_, contenido, nombre, mime, motivo):
    d = obtener(sesion, id_, True)
    if not d.activo:
        raise ErrorNegocio("Restaura el documento antes de agregar versiones", 409)
    return _nueva_version(sesion, usuario, d, contenido, nombre, mime, motivo)


def editar(sesion, usuario, id_, cambios, motivo):
    d = obtener(sesion, id_, True)
    if not d.activo:
        raise ErrorNegocio("Restaura el documento antes de editarlo", 409)
    datos = {**{c: getattr(d, c) for c in CAMPOS}, **cambios}
    validar_metadatos(sesion, datos)
    enlaces = sesion.scalars(
        select(AsistenciaHora)
        .join(DocumentoAsistencia)
        .join(VersionDocumento)
        .where(VersionDocumento.documento_id == d.id, DocumentoAsistencia.activo.is_(True))
    )
    for a in enlaces:
        _validar_vinculo(sesion, datos, a)
    antes = instantanea(d, CAMPOS)
    for k, v in cambios.items():
        setattr(d, k, v.strip() if isinstance(v, str) else v)
    d.nombre_normalizado = normalizar(d.nombre)
    auditar(
        sesion,
        usuario,
        "editar",
        "documento",
        d.id,
        antes,
        {**instantanea(d, CAMPOS), "motivo": motivo},
    )
    sesion.commit()
    return resumen(sesion, d)


def archivar(sesion, usuario, id_, activo, motivo):
    d = obtener(sesion, id_, True)
    antes = instantanea(d, CAMPOS)
    d.activo = activo
    auditar(
        sesion,
        usuario,
        "restaurar" if activo else "archivar",
        "documento",
        d.id,
        antes,
        {**instantanea(d, CAMPOS), "motivo": motivo},
    )
    sesion.commit()
    return resumen(sesion, d)


def contenido(sesion, usuario, id_, version_id, pagina=None):
    obtener(sesion, id_)
    v = version(sesion, id_, version_id)
    datos = almacen.previsualizar(v, pagina) if pagina is not None else almacen.leer(v)
    auditar(
        sesion,
        usuario,
        "visualizar" if pagina is not None else "descargar",
        "documento",
        id_,
        despues={"version_id": v.id, "pagina": pagina},
    )
    sesion.commit()
    return datos, v


def _validar_vinculo(sesion, datos, a):
    if not categoria(sesion, datos["categoria_id"]).admite_justificantes:
        raise ErrorNegocio("Esta categoría no admite justificantes de asistencia", 422)
    if datos.get("docente_id") is not None and datos["docente_id"] != a.docente_id:
        raise ErrorNegocio("El documento corresponde a otro docente", 409)
    if datos.get("periodo_id") is not None and datos["periodo_id"] != a.periodo_id:
        raise ErrorNegocio("El documento corresponde a otro periodo", 409)


def vincular(sesion, usuario, id_, version_id, asistencia_id, motivo, confirmar_transaccion=True):
    d = obtener(sesion, id_, True)
    if not d.activo:
        raise ErrorNegocio("No se vinculan documentos archivados", 409)
    v = version(sesion, id_, version_id)
    a = sesion.get(AsistenciaHora, asistencia_id)
    if a is None:
        raise NoEncontrado("La asistencia horaria")
    if a.fecha < hoy() and Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
        raise ErrorNegocio(
            "Vincular evidencia de días anteriores requiere asistencia.corregir", 403
        )
    _validar_vinculo(sesion, {c: getattr(d, c) for c in CAMPOS}, a)
    existente = sesion.scalar(
        select(DocumentoAsistencia).where(
            DocumentoAsistencia.version_id == v.id, DocumentoAsistencia.asistencia_id == a.id
        )
    )
    if existente and existente.activo:
        raise ErrorNegocio("El justificante ya está vinculado a esta hora", 409)
    if existente:
        existente.activo = True
        enlace = existente
    else:
        enlace = DocumentoAsistencia(
            version_id=v.id, asistencia_id=a.id, vinculado_por_id=usuario.id
        )
        sesion.add(enlace)
    sesion.flush()
    auditar(
        sesion,
        usuario,
        "vincular",
        "documento",
        d.id,
        despues={
            "vinculo_id": enlace.id,
            "version_id": v.id,
            "asistencia_id": a.id,
            "motivo": motivo,
        },
    )
    if confirmar_transaccion:
        sesion.commit()
    return {"id": enlace.id, "asistencia_id": a.id, "version_id": v.id, "activo": True}


def desvincular(sesion, usuario, id_, enlace_id, motivo):
    obtener(sesion, id_, True)
    enlace = sesion.scalar(
        select(DocumentoAsistencia)
        .join(VersionDocumento)
        .where(DocumentoAsistencia.id == enlace_id, VersionDocumento.documento_id == id_)
    )
    if enlace is None:
        raise NoEncontrado("El vínculo")
    a = sesion.get(AsistenciaHora, enlace.asistencia_id)
    if a.fecha < hoy() and Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
        raise ErrorNegocio("Se requiere asistencia.corregir para días anteriores", 403)
    enlace.activo = False
    auditar(
        sesion,
        usuario,
        "desvincular",
        "documento",
        id_,
        despues={"vinculo_id": enlace.id, "asistencia_id": enlace.asistencia_id, "motivo": motivo},
    )
    sesion.commit()
    return {"id": enlace.id, "activo": False}


def historial(sesion, usuario, id_):
    from app.models import Auditoria, Usuario

    obtener(sesion, id_)
    filas = list(
        sesion.scalars(
            select(Auditoria)
            .where(Auditoria.entidad == "documento", Auditoria.entidad_id == str(id_))
            .order_by(Auditoria.id)
        )
    )
    nombres = dict(sesion.execute(select(Usuario.id, Usuario.nombre)).all())
    ver_asistencia = Permiso.ASISTENCIA_VER in usuario.permisos
    salida = [
        {
            "fecha": a.fecha,
            "usuario": nombres.get(a.usuario_id, "—"),
            "accion": a.accion,
            "antes": a.antes
            if ver_asistencia or a.accion not in ("vincular", "desvincular")
            else None,
            "despues": a.despues
            if ver_asistencia or a.accion not in ("vincular", "desvincular")
            else None,
        }
        for a in filas
    ]
    auditar(sesion, usuario, "consultar_historial", "documento", id_)
    sesion.commit()
    return salida
