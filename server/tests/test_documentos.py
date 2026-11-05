"""Archivo privado con PDFs e imágenes generados, nunca documentos institucionales."""

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.archivos import almacen
from app.core.config import obtener_configuracion
from app.models import Documento, DocumentoAsistencia, VersionDocumento
from app.services import documentos as servicio
from app.services.comun import ErrorNegocio
from server.tests.test_asistencia_hora import capturar, ver

pytest_plugins = ["server.tests.test_asistencia_hora"]
pytestmark = pytest.mark.usefixtures("almacen_documentos")


def pdf_ficticio(texto="Documento ficticio versión 1"):
    with pymupdf.open() as doc:
        p = doc.new_page()
        p.insert_text((60, 70), texto)
        return doc.tobytes()


def imagen_ficticia(formato="PNG"):
    salida = io.BytesIO()
    Image.new("RGB", (100, 80), "white").save(salida, format=formato)
    return salida.getvalue()


def categoria(cliente, headers, clave="justificante"):
    r = cliente.get("/documentos/categorias", headers=headers)
    assert r.status_code == 200, r.text
    return next(c["id"] for c in r.json() if c["clave"] == clave)


def subir(cliente, headers, contenido=None, nombre="ficticio.pdf", mime="application/pdf", **datos):
    metadatos = {
        "nombre": "Justificante ficticio",
        "fecha": "2026-11-02",
        "categoria_id": categoria(cliente, headers),
        **datos,
    }
    return cliente.post(
        "/documentos",
        headers=headers,
        data={"datos": json.dumps(metadatos)},
        files={"archivo": (nombre, contenido if contenido is not None else pdf_ficticio(), mime)},
    )


def consulta(cliente, headers, id_):
    r = cliente.get(f"/documentos/{id_}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_carga_privada_consulta_vista_descarga_y_auditoria(cliente, como_admin, almacen_documentos):
    original = pdf_ficticio()
    r = subir(cliente, como_admin, original)
    assert r.status_code == 201, r.text
    d = consulta(cliente, como_admin, r.json()["documento_id"])
    assert d["version_actual"]["numero"] == 1 and d["version_actual"]["bytes"] == len(original)
    assert "clave" not in d["version_actual"] and str(almacen_documentos) not in str(d)
    objetos = [p for p in almacen_documentos.iterdir() if not p.name.startswith(".")]
    assert len(objetos) == 1 and len(objetos[0].name) == 32
    assert objetos[0].read_bytes() == original
    if os.name == "posix":
        assert objetos[0].stat().st_mode & 0o077 == 0
        assert almacen_documentos.stat().st_mode & 0o077 == 0
    ruta = f"/documentos/{d['id']}/versiones/{d['version_actual']['id']}"
    vista = cliente.get(ruta + "/vista", headers=como_admin)
    assert vista.status_code == 200 and vista.content.startswith(b"\x89PNG")
    descarga = cliente.get(ruta + "/descargar", headers=como_admin)
    assert descarga.content == original and descarga.headers["cache-control"] == "no-store"
    assert descarga.headers["x-content-type-options"] == "nosniff"
    historial = cliente.get(f"/documentos/{d['id']}/historial", headers=como_admin).json()
    assert {"crear", "subir", "consultar", "visualizar", "descargar"} <= {
        h["accion"] for h in historial
    }


@pytest.mark.parametrize(
    "formato,nombre,mime", [("PNG", "scan.png", "image/png"), ("JPEG", "scan.jpg", "image/jpeg")]
)
def test_imagenes_se_validan_y_se_previsualizan(cliente, como_admin, formato, nombre, mime):
    r = subir(cliente, como_admin, imagen_ficticia(formato), nombre, mime)
    assert r.status_code == 201, r.text
    d = r.json()
    vista = cliente.get(
        f"/documentos/{d['documento_id']}/versiones/{d['version']['id']}/vista", headers=como_admin
    )
    assert vista.status_code == 200
    with Image.open(io.BytesIO(vista.content)) as img:
        assert img.format == "PNG" and img.size == (100, 80)


def test_versiones_conservadas_y_vista_de_version_anterior(cliente, como_admin):
    uno = pdf_ficticio("Primera versión ficticia")
    dos = pdf_ficticio("Segunda versión ficticia")
    d = subir(cliente, como_admin, uno).json()
    r = cliente.post(
        f"/documentos/{d['documento_id']}/versiones",
        headers=como_admin,
        data={"motivo": "Corrección ficticia del archivo"},
        files={"archivo": ("ficticio-v2.pdf", dos, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    detalle = consulta(cliente, como_admin, d["documento_id"])
    assert [v["numero"] for v in detalle["versiones"]] == [2, 1]
    for v, original in zip(detalle["versiones"], [dos, uno], strict=True):
        r = cliente.get(
            f"/documentos/{d['documento_id']}/versiones/{v['id']}/descargar", headers=como_admin
        )
        assert r.content == original
    assert (
        cliente.post(
            f"/documentos/{d['documento_id']}/versiones",
            headers=como_admin,
            data={"motivo": "Mismo archivo ficticio"},
            files={"archivo": ("copia.pdf", dos, "application/pdf")},
        ).status_code
        == 409
    )


def test_filtros_nombre_docente_periodo_fecha_categoria_y_paginacion(
    cliente, como_admin, escuela_horas
):
    e = escuela_horas
    r = subir(cliente, como_admin, docente_id=e["docente"], periodo_id=e["periodo"])
    assert r.status_code == 201
    id_ = r.json()["documento_id"]
    params = {
        "texto": "justificánte",
        "docente_nombre": "prueba uno",
        "periodo_id": e["periodo"],
        "desde": "2026-11-02",
        "hasta": "2026-11-02",
        "categoria_id": categoria(cliente, como_admin),
    }
    r = cliente.get("/documentos", headers=como_admin, params=params)
    assert r.status_code == 200 and [d["id"] for d in r.json()["resultados"]] == [id_]
    for campo, valor in [
        ("docente_id", e["docente2"]),
        ("periodo_id", 999),
        ("desde", "2026-11-03"),
        ("texto", "' OR 1=1 --"),
        ("docente_nombre", "desconocido"),
    ]:
        d = cliente.get("/documentos", headers=como_admin, params={**params, campo: valor})
        assert d.status_code in (200, 422)
        if d.status_code == 200:
            assert d.json()["total"] == 0
    assert (
        cliente.get("/documentos", headers=como_admin, params={"limite": 1, "offset": 1}).json()[
            "resultados"
        ]
        == []
    )


def test_archivar_y_restaurar_sin_eliminar_versiones(cliente, como_admin):
    d = subir(cliente, como_admin).json()
    id_ = d["documento_id"]
    assert (
        cliente.post(
            f"/documentos/{id_}/archivar",
            headers=como_admin,
            json={"motivo": "Archivo ficticio finalizado"},
        ).status_code
        == 200
    )
    assert cliente.get("/documentos", headers=como_admin).json()["total"] == 0
    assert (
        cliente.get("/documentos", headers=como_admin, params={"incluir_archivados": True}).json()[
            "total"
        ]
        == 1
    )
    assert len(consulta(cliente, como_admin, id_)["versiones"]) == 1
    assert cliente.delete(f"/documentos/{id_}", headers=como_admin).status_code == 405
    assert (
        cliente.post(
            f"/documentos/{id_}/restaurar",
            headers=como_admin,
            json={"motivo": "Restauración ficticia autorizada"},
        ).status_code
        == 200
    )


def test_lector_puede_ver_pero_no_descargar_o_modificar(cliente, como_admin, como_consulta):
    d = subir(cliente, como_admin).json()
    id_, vid = d["documento_id"], d["version"]["id"]
    assert cliente.get(f"/documentos/{id_}", headers=como_consulta).status_code == 200
    assert (
        cliente.get(f"/documentos/{id_}/versiones/{vid}/vista", headers=como_consulta).status_code
        == 200
    )
    assert (
        cliente.get(
            f"/documentos/{id_}/versiones/{vid}/descargar", headers=como_consulta
        ).status_code
        == 403
    )
    assert (
        cliente.post(
            f"/documentos/{id_}/archivar", headers=como_consulta, json={"motivo": "No autorizado"}
        ).status_code
        == 403
    )
    assert cliente.get(f"/documentos/{id_}").status_code == 401
    assert cliente.get(f"/documentos/{id_}/versiones/{vid}/descargar").status_code == 401


def test_version_ajena_no_se_puede_consultar_mediante_otro_documento(cliente, como_admin):
    a = subir(cliente, como_admin).json()
    b = subir(cliente, como_admin, pdf_ficticio("Otro documento")).json()
    for ruta in ("vista", "descargar"):
        r = cliente.get(
            f"/documentos/{a['documento_id']}/versiones/{b['version']['id']}/{ruta}",
            headers=como_admin,
        )
        assert r.status_code == 404


@pytest.mark.parametrize(
    "nombre",
    [
        "../fuera.pdf",
        "C:\\privado.pdf",
        "documento.exe",
        "foto.svg",
        "documento.pdf.exe",
        "CON.pdf",
        "ficticio\x00.pdf",
        "oculto\u202e.pdf",
    ],
)
def test_nombres_inseguros_se_rechazan_sin_publicar(cliente, como_admin, sesion, nombre):
    if "\x00" in nombre:
        with pytest.raises(ErrorNegocio):
            almacen.nombre_seguro(nombre)
        return
    r = subir(cliente, como_admin, nombre=nombre)
    if "\\" in nombre:
        # Multipart normaliza rutas absolutas enviadas por clientes Windows.
        with pytest.raises(ErrorNegocio):
            almacen.nombre_seguro(nombre)
        assert r.status_code == 201 and r.json()["version"]["nombre_original"] == "privado.pdf"
        return
    assert r.status_code == 422, r.text
    assert sesion.scalar(select(Documento.id)) is None


@pytest.mark.parametrize(
    "contenido,nombre,mime",
    [
        (b"MZcontenido ejecutable", "falso.pdf", "application/pdf"),
        (b"<svg><script>alert(1)</script></svg>", "falso.png", "image/png"),
        (b"%PDF-archivo truncado", "truncado.pdf", "application/pdf"),
        (b"", "vacio.pdf", "application/pdf"),
    ],
)
def test_contenido_invalido_no_crea_documentos(
    cliente, como_admin, sesion, contenido, nombre, mime
):
    r = subir(cliente, como_admin, contenido, nombre, mime)
    assert r.status_code in (413, 422), r.text
    assert sesion.scalar(select(Documento.id)) is None


def test_extension_mime_y_contenido_deben_coincidir(cliente, como_admin):
    assert (
        subir(cliente, como_admin, imagen_ficticia(), "foto.pdf", "application/pdf").status_code
        == 422
    )
    assert (
        subir(cliente, como_admin, pdf_ficticio(), "ficticio.pdf", "image/png").status_code == 422
    )


def test_pdf_activo_cifrado_y_adjunto_se_rechazan(cliente, como_admin):
    with pymupdf.open() as pdf:
        p = pdf.new_page()
        p.insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(10, 10, 80, 30),
                "uri": "https://ficticio.invalid",
            }
        )
        activo = pdf.tobytes()
    assert subir(cliente, como_admin, activo).status_code == 422
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.embfile_add("ficticio.txt", b"ficticio")
        adjunto = pdf.tobytes()
    assert subir(cliente, como_admin, adjunto).status_code == 422
    with pymupdf.open() as pdf:
        pdf.new_page()
        cifrado = pdf.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="ficticia", owner_pw="ficticia"
        )
    assert subir(cliente, como_admin, cifrado).status_code == 422


def test_limites_antes_de_publicar_y_con_chunked(cliente, como_admin, monkeypatch):
    monkeypatch.setattr(obtener_configuracion(), "archivo_max_mb", 1)
    r = subir(cliente, como_admin, b"%PDF-" + b"0" * (1024 * 1024))
    assert r.status_code == 413
    r = cliente.post(
        "/documentos", headers={**como_admin, "Content-Length": str(2 * 1024 * 1024)}, content=b"x"
    )
    assert r.status_code == 413

    def bloques():
        yield b"x" * (700 * 1024)
        yield b"y" * (700 * 1024)

    r = cliente.post(
        "/documentos",
        headers={**como_admin, "Content-Type": "multipart/form-data; boundary=a"},
        content=bloques(),
    )
    assert r.status_code in (400, 413)


def test_integridad_y_symlinks(cliente, como_admin, almacen_documentos, sesion):
    d = subir(cliente, como_admin).json()
    v = sesion.get(VersionDocumento, d["version"]["id"])
    ruta = almacen_documentos / v.clave
    ruta.write_bytes(b"contenido ficticio alterado")
    endpoint = f"/documentos/{d['documento_id']}/versiones/{v.id}/descargar"
    assert cliente.get(endpoint, headers=como_admin).status_code == 409
    with pytest.raises(ErrorNegocio):
        almacen.ruta_objeto("../ficticio")
    if os.name == "posix":
        ruta.unlink()
        otra = almacen_documentos / "objetivo-ficticio"
        otra.write_bytes(b"ficticio")
        ruta.symlink_to(otra)
        assert cliente.get(endpoint, headers=como_admin).status_code == 409


def test_pruebas_no_pueden_usar_almacen_real_o_repositorio(monkeypatch, tmp_path):
    cfg = obtener_configuracion()
    for ruta in (Path.cwd() / "datos", "ruta-relativa", tmp_path / "sin-marcador"):
        monkeypatch.setattr(cfg, "archivo_raiz", Path(ruta))
        with pytest.raises(ErrorNegocio):
            almacen.raiz()


def test_antivirus_falla_cerrado_y_rechaza_infeccion(
    cliente, como_admin, monkeypatch, almacen_documentos
):
    cfg = obtener_configuracion()
    monkeypatch.setattr(cfg, "archivo_requerir_antivirus", True)
    assert subir(cliente, como_admin).status_code == 503
    assert [p for p in almacen_documentos.iterdir() if not p.name.startswith(".")] == []
    monkeypatch.setattr(cfg, "archivo_antivirus_cmd", Path(__file__).resolve())
    real = almacen.subprocess.run

    def ejecutar(comando, **kwargs):
        if str(comando[0]) == str(Path(__file__).resolve()):
            return SimpleNamespace(returncode=1)
        return real(comando, **kwargs)

    monkeypatch.setattr(almacen.subprocess, "run", ejecutar)
    assert subir(cliente, como_admin).status_code == 422
    assert [p for p in almacen_documentos.iterdir() if not p.name.startswith(".")] == []
    assert subir(cliente, como_admin, b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE").status_code == 422


def test_versiones_inmutables_y_borrado_prohibido_en_postgresql(cliente, como_admin, sesion):
    d = subir(cliente, como_admin).json()
    for sql in (
        "UPDATE documento_version SET numero=9",
        "DELETE FROM documento_version",
        "DELETE FROM documento",
    ):
        with pytest.raises(DBAPIError), sesion.begin_nested():
            sesion.execute(text(sql))
    assert consulta(cliente, como_admin, d["documento_id"])["version_actual"]["numero"] == 1


def test_justificante_se_vincula_a_version_exacta_sin_cambiar_asistencia(
    cliente, como_admin, escuela_horas, sesion
):
    e = escuela_horas
    a = capturar(cliente, como_admin, ver(cliente, como_admin)["filas"][0], "falto").json()
    doc = subir(cliente, como_admin, docente_id=e["docente"], periodo_id=e["periodo"]).json()
    id_ = doc["documento_id"]
    datos = {
        "version_id": doc["version"]["id"],
        "asistencia_id": a["id"],
        "motivo": "Justificante ficticio recibido",
    }
    r = cliente.post(f"/documentos/{id_}/vinculos", headers=como_admin, json=datos)
    assert r.status_code == 201, r.text
    assert ver(cliente, como_admin)["filas"][0]["estado"] == "falto"
    assert (
        cliente.post(f"/documentos/{id_}/vinculos", headers=como_admin, json=datos).status_code
        == 409
    )
    d = cliente.get("/documentos", headers=como_admin, params={"asistencia_id": a["id"]}).json()
    assert [f["id"] for f in d["resultados"]] == [id_]
    cliente.post(
        f"/documentos/{id_}/versiones",
        headers=como_admin,
        data={"motivo": "Otra versión ficticia"},
        files={"archivo": ("v2.pdf", pdf_ficticio("Segunda versión"), "application/pdf")},
    )
    vinculos = consulta(cliente, como_admin, id_)["asistencias"]
    assert vinculos[0]["version_id"] == doc["version"]["id"]
    enlace_id = vinculos[0]["id"]
    assert (
        cliente.post(
            f"/documentos/{id_}/vinculos/{enlace_id}/anular",
            headers=como_admin,
            json={"motivo": "Corrección ficticia del vínculo"},
        ).status_code
        == 200
    )
    assert not sesion.get(DocumentoAsistencia, enlace_id).activo
    assert len(consulta(cliente, como_admin, id_)["versiones"]) == 2


def test_vinculos_incompatibles_y_metadatos_se_rechazan(cliente, como_admin, escuela_horas):
    e = escuela_horas
    a = capturar(cliente, como_admin, ver(cliente, como_admin)["filas"][0]).json()
    doc = subir(cliente, como_admin, docente_id=e["docente2"]).json()
    payload = {
        "version_id": doc["version"]["id"],
        "asistencia_id": a["id"],
        "motivo": "Prueba ficticia",
    }
    assert (
        cliente.post(
            f"/documentos/{doc['documento_id']}/vinculos", headers=como_admin, json=payload
        ).status_code
        == 409
    )
    doc = subir(cliente, como_admin, docente_id=e["docente"]).json()
    payload["version_id"] = doc["version"]["id"]
    assert (
        cliente.post(
            f"/documentos/{doc['documento_id']}/vinculos", headers=como_admin, json=payload
        ).status_code
        == 201
    )
    assert (
        cliente.patch(
            f"/documentos/{doc['documento_id']}",
            headers=como_admin,
            json={"docente_id": e["docente2"], "motivo": "Cambio incompatible ficticio"},
        ).status_code
        == 409
    )


def test_almacen_no_adopta_carpetas_ajenas_ni_comparte_bases(monkeypatch, tmp_path):
    cfg = obtener_configuracion()
    ajena = tmp_path / "carpeta-ajena"
    ajena.mkdir()
    (ajena / ".asi-archivo-pruebas").write_text("ASI-ARCHIVO-PRUEBAS")
    existente = ajena / "conservar-ficticio.txt"
    existente.write_text("No modificar este contenido ficticio")
    monkeypatch.setattr(cfg, "archivo_raiz", ajena)
    with pytest.raises(ErrorNegocio):
        almacen.raiz()
    assert existente.read_text() == "No modificar este contenido ficticio"
    nueva = tmp_path / "nueva-dedicada"
    monkeypatch.setattr(cfg, "archivo_raiz", nueva)
    monkeypatch.setattr(almacen, "en_pruebas", lambda: False)
    monkeypatch.setattr(
        cfg, "database_url", "postgresql+psycopg://ficticio@localhost/base_ficticia_uno"
    )
    almacen.raiz()
    marcador = (nueva / ".asi-archivo-almacen").read_text()
    monkeypatch.setattr(
        cfg, "database_url", "postgresql+psycopg://ficticio@localhost/base_ficticia_dos"
    )
    with pytest.raises(ErrorNegocio):
        almacen.raiz()
    assert (nueva / ".asi-archivo-almacen").read_text() == marcador


def test_categorias_y_metadatos_con_motivo_y_auditoria(cliente, como_admin, como_consulta):
    r = cliente.post(
        "/documentos/categorias",
        headers=como_admin,
        json={"clave": "acta_ficticia", "nombre": "Acta ficticia"},
    )
    assert r.status_code == 201, r.text
    assert (
        cliente.post(
            "/documentos/categorias",
            headers=como_consulta,
            json={"clave": "no_autorizada", "nombre": "No autorizada"},
        ).status_code
        == 403
    )
    d = subir(cliente, como_admin, categoria_id=r.json()["id"]).json()
    id_ = d["documento_id"]
    assert (
        cliente.patch(
            f"/documentos/{id_}",
            headers=como_admin,
            json={
                "nombre": "Nombre ficticio corregido",
                "descripcion": "Nota ficticia",
                "motivo": "Corrección ficticia del título",
            },
        ).status_code
        == 200
    )
    assert (
        cliente.get(
            "/documentos", headers=como_admin, params={"texto": "nombre ficticio corregido"}
        ).json()["total"]
        == 1
    )
    assert (
        cliente.patch(
            f"/documentos/{id_}", headers=como_admin, json={"nombre": "No cambia sin motivo"}
        ).status_code
        == 422
    )
    assert (
        cliente.post(
            f"/documentos/{id_}/archivar", headers=como_admin, json={"motivo": "     "}
        ).status_code
        == 422
    )
    acciones = cliente.get(f"/documentos/{id_}/historial", headers=como_admin).json()
    assert any(
        a["accion"] == "editar" and a["antes"]["nombre"] == "Justificante ficticio"
        for a in acciones
    )


def test_produccion_no_puede_omitir_antivirus(cliente, como_admin, monkeypatch):
    cfg = obtener_configuracion()
    monkeypatch.setattr(cfg, "entorno", "produccion")
    monkeypatch.setattr(cfg, "archivo_requerir_antivirus", False)
    assert subir(cliente, como_admin).status_code == 503


def test_pdf_con_imagen_incrustada_excesiva_no_se_renderiza(cliente, como_admin):
    with pymupdf.open() as pdf:
        p = pdf.new_page()
        xref = p.insert_image(pymupdf.Rect(10, 10, 100, 100), stream=imagen_ficticia())
        pdf.xref_set_key(xref, "Width", "100000")
        contenido = pdf.tobytes()
    assert subir(cliente, como_admin, contenido).status_code == 422


def test_antivirus_no_puede_cambiar_objeto_publicado(
    cliente, como_admin, monkeypatch, almacen_documentos
):
    monkeypatch.setattr(almacen, "_antivirus", lambda ruta: ruta.write_bytes(b"cambio ficticio"))
    assert subir(cliente, como_admin).status_code == 409
    assert [p for p in almacen_documentos.iterdir() if not p.name.startswith(".")] == []


def test_vinculos_no_revelan_asistencia_sin_su_permiso(
    cliente, como_admin, como_consulta, consulta, sesion, escuela_horas
):
    a = capturar(cliente, como_admin, ver(cliente, como_admin)["filas"][0], "falto").json()
    d = subir(cliente, como_admin).json()
    assert (
        cliente.post(
            f"/documentos/{d['documento_id']}/vinculos",
            headers=como_admin,
            json={
                "version_id": d["version"]["id"],
                "asistencia_id": a["id"],
                "motivo": "Evidencia ficticia",
            },
        ).status_code
        == 201
    )
    rol = consulta.roles[0]
    permisos_originales = list(rol.permisos)
    try:
        rol.permisos = [p for p in permisos_originales if p.clave != "asistencia.ver"]
        sesion.commit()
        detalle = cliente.get(f"/documentos/{d['documento_id']}", headers=como_consulta).json()
        assert detalle["asistencias"] == []
        h = cliente.get(f"/documentos/{d['documento_id']}/historial", headers=como_consulta).json()
        assert next(x for x in h if x["accion"] == "vincular")["despues"] is None
        assert (
            cliente.get(
                "/documentos", headers=como_consulta, params={"asistencia_id": a["id"]}
            ).status_code
            == 403
        )
    finally:
        rol.permisos = permisos_originales
        sesion.commit()


def test_antivirus_limpio_publica_y_error_impide_publicacion(
    cliente, como_admin, monkeypatch, almacen_documentos
):
    cfg = obtener_configuracion()
    monkeypatch.setattr(cfg, "archivo_antivirus_cmd", Path(__file__).resolve())
    real = almacen.subprocess.run
    codigo = [2]

    def ejecutar(comando, **kwargs):
        if str(comando[0]) == str(Path(__file__).resolve()):
            assert comando[1:3] == ["--no-summary", "--"]
            assert Path(comando[3]).parent == almacen_documentos
            return SimpleNamespace(returncode=codigo[0])
        return real(comando, **kwargs)

    monkeypatch.setattr(almacen.subprocess, "run", ejecutar)
    assert subir(cliente, como_admin).status_code == 503
    codigo[0] = 0
    assert subir(cliente, como_admin).status_code == 201


def test_confirmacion_incierta_no_borra_un_original_publicado(
    sesion, admin, cliente, como_admin, monkeypatch, almacen_documentos
):
    categoria_id = categoria(cliente, como_admin)
    confirmar = sesion.commit

    def confirmacion_incierta():
        confirmar()
        raise ConnectionError("Resultado ficticio incierto después de confirmar")

    monkeypatch.setattr(sesion, "commit", confirmacion_incierta)
    from datetime import date

    original = pdf_ficticio()
    with pytest.raises(ConnectionError):
        servicio.crear(
            sesion,
            admin,
            {
                "nombre": "Confirmación ficticia",
                "fecha": date(2026, 11, 2),
                "categoria_id": categoria_id,
            },
            original,
            "ficticio.pdf",
            "application/pdf",
        )
    v = sesion.scalar(select(VersionDocumento))
    assert v is not None
    assert (almacen_documentos / v.clave).read_bytes() == original
