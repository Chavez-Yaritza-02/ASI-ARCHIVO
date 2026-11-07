"""Importación de horarios desde PDF de punta a punta: API real + OCR real (Tesseract)
sobre documentos FICTICIOS generados en horario_ficticio.py."""

import os
from dataclasses import replace

import pytest
from horario_ficticio import DOS, UNO, Clase, pdf_escaneado, zip_con
from sqlalchemy import select

from app.models import Auditoria

os.environ["ASI_OCR_PROCESOS"] = "1"  # en pruebas, OCR en el mismo proceso


@pytest.fixture
def catalogo(cliente, como_admin):
    """Periodo activo y catálogos parciales: algunas cosas coinciden y otras no."""

    def crear(ruta, datos):
        r = cliente.post(ruta, json=datos, headers=como_admin)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    periodo = crear(
        "/periodos",
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    cliente.post(f"/periodos/{periodo}/activar", headers=como_admin)
    return {
        "periodo": periodo,
        "uno": crear("/docentes", {"nombre": "DOCENTE PRUEBA UNO", "nomina": "ZZX0001"}),
        "calculo": crear("/asignaturas", {"nombre": "CÁLC. DIF."}),
        "gestion": crear("/asignaturas", {"nombre": "GESTIÓN ACADÉMICA", "tipo": "actividad"}),
        "tutoria": crear("/asignaturas", {"nombre": "TUTORÍA INDIVIDUAL", "tipo": "actividad"}),
        "m01": crear("/aulas", {"clave": "M01"}),
        "m05": crear("/aulas", {"clave": "M05"}),
        "sala": crear("/aulas", {"clave": "Sala EM"}),
        "dom03": crear("/aulas", {"clave": "DOM-03"}),
        "grupo_a": crear(
            "/grupos", {"letra": "A", "periodo_id": periodo, "carrera": "IEM", "semestre": 3}
        ),
    }


def subir(cliente, encabezados, periodo_id, nombre, contenido):
    tipo = "application/zip" if nombre.endswith(".zip") else "application/pdf"
    return cliente.post(
        "/importaciones",
        data={"periodo_id": str(periodo_id)},
        files={"archivo": (nombre, contenido, tipo)},
        headers=encabezados,
    )


def importar(cliente, encabezados, periodo_id, nombre, contenido) -> dict:
    """Sube el archivo; el TestClient espera a que termine la tarea en segundo plano."""
    r = subir(cliente, encabezados, periodo_id, nombre, contenido)
    assert r.status_code == 202, r.text
    return cliente.get(f"/importaciones/{r.json()['id']}", headers=encabezados).json()


def paginas(detalle: dict) -> list[dict]:
    return [p for d in detalle["documentos"] for p in d["paginas"]]


def pagina(cliente, encabezados, id_) -> dict:
    return cliente.get(f"/importaciones/paginas/{id_}", headers=encabezados).json()


def celda(detalle: dict, dia: str, hora: int) -> dict:
    return next(c for c in detalle["celdas_detalle"] if c["dia"] == dia and c["hora"] == hora)


# Variante de UNO con errores típicos de OCR y una materia que no está en el catálogo.
UNO_CON_ERRORES = replace(
    UNO,
    clases=[
        Clase(0, 7, "CALC. DIF.", "A", "M01"),
        Clase(0, 8, "CALC. DIF.", "A", "M01"),
        Clase(0, 9, "GESTION ACADEMIC", None, "SALA EM"),  # asignatura parecida
        Clase(2, 7, "FIS. GRAL", "B", "MOS"),  # materia nueva; aula "MOS" ~ M05
        Clase(4, 10, "TUTORIA INDIVIDUAL", None, "DOM-03"),
    ],
)


def test_importar_zip_deja_propuestas_por_revisar(cliente, como_admin, catalogo):
    detalle = importar(
        cliente,
        como_admin,
        catalogo["periodo"],
        "horarios.zip",
        zip_con(
            {
                "uno.pdf": pdf_escaneado(UNO_CON_ERRORES),
                "dos.pdf": pdf_escaneado(DOS),
                "lista.txt": b"x",
            }
        ),
    )
    assert detalle["estado"] == "en_revision"
    assert detalle["total_documentos"] == 2 and detalle["procesados"] == 2
    assert detalle["conteo"] == {"por_revisar": 2}

    uno = pagina(cliente, como_admin, paginas(detalle)[1]["id"])  # orden alfabético: dos, uno
    assert uno["docente"]["id"] == catalogo["uno"] and uno["docente_estado"] == "coincide"
    assert uno["version_documento"] == 1 and uno["fecha_documento"] == "2026-06-28"
    assert uno["horas_qr"] == 5 and len(uno["celdas_detalle"]) == 5

    calc = celda(uno, "lunes", 7)
    assert (calc["asignatura_id"], calc["asignatura_estado"]) == (catalogo["calculo"], "coincide")
    assert (calc["aula_id"], calc["aula_estado"]) == (catalogo["m01"], "coincide")
    # La letra no identifica al grupo: queda pendiente aunque exista un grupo "A".
    assert (calc["grupo_id"], calc["grupo_letra"], calc["grupo_estado"]) == (None, "A", "pendiente")

    gestion = celda(uno, "lunes", 9)
    assert (gestion["asignatura_id"], gestion["asignatura_estado"]) == (
        catalogo["gestion"],
        "sugerido",
    )
    fisica = celda(uno, "miercoles", 7)
    assert (fisica["asignatura_id"], fisica["asignatura_estado"]) == (None, "sin_coincidencia")
    assert (fisica["aula_id"], fisica["aula_estado"]) == (catalogo["m05"], "sugerido")
    assert fisica["texto_ocr"] and fisica["aula_texto"] == "MOS"

    # Docente sin registro: no se inventa, queda por elegir.
    dos = pagina(cliente, como_admin, paginas(detalle)[0]["id"])
    assert dos["docente"] is None and dos["docente_texto"] == "DOCENTE PRUEBA DOS"
    assert "Elige el docente" in dos["lista_pendientes"]


def test_no_se_aprueba_sin_revision_y_al_aprobar_solo_se_crea_borrador(
    cliente, como_admin, catalogo
):
    detalle = importar(
        cliente, como_admin, catalogo["periodo"], "uno.pdf", pdf_escaneado(UNO_CON_ERRORES)
    )
    id_ = paginas(detalle)[0]["id"]
    r = cliente.post(f"/importaciones/paginas/{id_}/aprobar", json={}, headers=como_admin)
    assert r.status_code == 422
    assert any("elige la asignatura" in p for p in r.json()["problemas"])
    assert any("confirma el aula sugerida" in p for p in r.json()["problemas"])

    # El usuario crea la materia que faltaba (acción explícita) y la asigna.
    fisica = cliente.post("/asignaturas", json={"nombre": "FIS. GRAL"}, headers=como_admin).json()[
        "id"
    ]
    detalle_pagina = pagina(cliente, como_admin, id_)
    celdas = [
        {
            "id": c["id"],
            "dia": c["dia"],
            "hora": c["hora"],
            "asignatura_id": fisica if c["asignatura_id"] is None else c["asignatura_id"],
            "aula_id": c["aula_id"],
            "grupo_id": c["grupo_id"],
            "grupo_letra": c["grupo_letra"],
        }
        for c in detalle_pagina["celdas_detalle"]
    ]
    r = cliente.put(f"/importaciones/paginas/{id_}", json={"celdas": celdas}, headers=como_admin)
    assert len(r.json()["lista_pendientes"]) == 2  # quedan dos sugerencias sin aceptar
    # Aceptar de golpe no toma las aproximadas (aula «MOS» ~ M05, «GESTION» parecida).
    r = cliente.post(f"/importaciones/paginas/{id_}/aceptar-sugerencias", headers=como_admin)
    assert len(r.json()["lista_pendientes"]) == 2
    # Se confirman una por una: el usuario revisa cada celda y la acepta.
    for c in celdas:
        c["confirmar"] = True
    r = cliente.put(f"/importaciones/paginas/{id_}", json={"celdas": celdas}, headers=como_admin)
    assert r.json()["lista_pendientes"] == []

    r = cliente.post(f"/importaciones/paginas/{id_}/aprobar", json={}, headers=como_admin)
    assert r.status_code == 200, r.text
    horario = r.json()
    assert horario["estado"] == "borrador" and horario["origen"] == "pdf"
    assert horario["version_documento"] == 1 and horario["fecha_documento"] == "2026-06-28"
    bloques = [(b["dia"], b["hora_inicio"], b["hora_fin"]) for b in horario["bloques"]]
    assert ("lunes", "07:00:00", "09:00:00") in bloques  # 7 y 8 se unen en un bloque
    assert horario["horas"] == 5
    assert horario["bloques"][0]["grupo_letra"] == "A"
    assert any(
        "pendiente de validación" in a
        for a in cliente.get(f"/horarios/{horario['id']}", headers=como_admin).json()[
            "advertencias"
        ]
    )

    assert pagina(cliente, como_admin, id_)["estado"] == "aprobada"
    detalle = cliente.get(f"/importaciones/{detalle['id']}", headers=como_admin).json()
    assert detalle["estado"] == "terminada"
    # Una página aprobada ya no se edita.
    r = cliente.put(f"/importaciones/paginas/{id_}", json={"celdas": []}, headers=como_admin)
    assert r.status_code == 409


def test_corregir_docente_dias_horas_y_grupo(cliente, como_admin, catalogo, sesion):
    detalle = importar(cliente, como_admin, catalogo["periodo"], "dos.pdf", pdf_escaneado(DOS))
    id_ = paginas(detalle)[0]["id"]
    original = pagina(cliente, como_admin, id_)
    dinamica = cliente.post("/asignaturas", json={"nombre": "DINAMICA"}, headers=como_admin).json()[
        "id"
    ]
    lmac = cliente.post("/aulas", json={"clave": "LMAC"}, headers=como_admin).json()["id"]
    dos = cliente.post(
        "/docentes", json={"nombre": "DOCENTE PRUEBA DOS"}, headers=como_admin
    ).json()["id"]

    martes_15 = celda(original, "martes", 15)
    nuevas = [
        # Se conserva la celda leída, pero se mueve al jueves 9:00 y se le asigna grupo completo.
        {
            "id": martes_15["id"],
            "dia": "jueves",
            "hora": 9,
            "asignatura_id": dinamica,
            "aula_id": lmac,
            "grupo_id": catalogo["grupo_a"],
        },
        # Celda que el OCR no leyó, capturada a mano.
        {"dia": "viernes", "hora": 7, "asignatura_id": catalogo["gestion"], "aula_id": None},
    ]  # las demás celdas leídas se eliminan
    r = cliente.put(
        f"/importaciones/paginas/{id_}",
        json={"docente_id": dos, "celdas": nuevas},
        headers=como_admin,
    )
    assert r.status_code == 200, r.text
    revisada = r.json()
    assert revisada["docente_estado"] == "confirmado"
    assert [(c["dia"], c["hora"], c["origen"]) for c in revisada["celdas_detalle"]] == [
        ("jueves", 9, "ocr"),
        ("viernes", 7, "manual"),
    ]
    movida = revisada["celdas_detalle"][0]
    assert movida["texto_ocr"] == martes_15["texto_ocr"]  # la evidencia se conserva
    assert (movida["grupo_estado"], movida["grupo_letra"]) == ("confirmado", None)
    assert revisada["lista_pendientes"] == []
    assert any("indica 3 h y hay 2" in a for a in revisada["avisos"])

    # Dos actividades en la misma hora: error.
    doble = [nuevas[1], {**nuevas[1], "asignatura_id": dinamica}]
    r = cliente.put(f"/importaciones/paginas/{id_}", json={"celdas": doble}, headers=como_admin)
    assert r.status_code == 422

    # Aprobar con menos horas que el documento exige confirmarlo.
    r = cliente.post(f"/importaciones/paginas/{id_}/aprobar", json={}, headers=como_admin)
    assert r.status_code == 409 and "horas" in r.json()["detail"]
    r = cliente.post(
        f"/importaciones/paginas/{id_}/aprobar",
        json={"aceptar_diferencia_horas": True},
        headers=como_admin,
    )
    assert r.status_code == 200

    acciones = sesion.scalars(
        select(Auditoria.accion)
        .where(Auditoria.entidad.in_(["importacion", "importacion_pagina"]))
        .order_by(Auditoria.id)
    )
    assert list(acciones) == ["importar", "revisar", "aprobar"]


def test_archivo_ya_importado_y_copias_en_el_mismo_pdf(cliente, como_admin, catalogo):
    archivo = pdf_escaneado(UNO, UNO)  # dos copias de la misma hoja
    primera = importar(cliente, como_admin, catalogo["periodo"], "uno.pdf", archivo)
    estados = [p["estado"] for p in paginas(primera)]
    assert estados == ["por_revisar", "duplicada"]
    assert paginas(primera)[1]["duplicado_de_id"] == paginas(primera)[0]["id"]

    # El mismo archivo otra vez: se detecta por su huella y no se procesa.
    r = subir(cliente, como_admin, catalogo["periodo"], "copia.pdf", archivo)
    assert r.json()["estado"] == "terminada"
    segunda = cliente.get(f"/importaciones/{r.json()['id']}", headers=como_admin).json()
    assert segunda["documentos"][0]["estado"] == "duplicado"
    assert "Idéntico a uno.pdf" in segunda["documentos"][0]["mensaje"]

    # Una copia restaurada se puede revisar si se necesita.
    copia = paginas(primera)[1]["id"]
    r = cliente.post(f"/importaciones/paginas/{copia}/restaurar", headers=como_admin)
    assert r.json()["estado"] == "por_revisar"


def test_mismo_documento_aprobado_dos_veces_pide_confirmacion(cliente, como_admin, catalogo):
    def aprobar_importacion(contenido, nombre, **opciones):
        detalle = importar(cliente, como_admin, catalogo["periodo"], nombre, contenido)
        id_ = paginas(detalle)[0]["id"]
        cliente.post(f"/importaciones/paginas/{id_}/aceptar-sugerencias", headers=como_admin)
        fis = pagina(cliente, como_admin, id_)
        return (
            id_,
            cliente.post(
                f"/importaciones/paginas/{id_}/aprobar", json=opciones, headers=como_admin
            ),
            fis,
        )

    fisica = cliente.post("/asignaturas", json={"nombre": "FIS. GRAL"}, headers=como_admin).json()[
        "id"
    ]
    assert fisica
    _, r, _ = aprobar_importacion(pdf_escaneado(UNO), "uno.pdf")
    assert r.status_code == 200, r.text
    # Mismo docente, versión y fecha, pero otro archivo (otro escaneo): ya se importó.
    otro = replace(UNO, clases=[*UNO.clases[:4]], extra_horas_qr=1)
    id_, r, detalle = aprobar_importacion(
        pdf_escaneado(otro), "uno_otra_vez.pdf", aceptar_diferencia_horas=True
    )
    assert any("ya se importó" in a for a in detalle["avisos"])
    assert r.status_code == 409 and r.json()["detail"] == "Este documento ya se importó"
    r = cliente.post(
        f"/importaciones/paginas/{id_}/aprobar",
        json={"aceptar_diferencia_horas": True, "permitir_duplicado": True},
        headers=como_admin,
    )
    assert r.status_code == 200 and r.json()["version"] == 2


def test_pagina_sin_qr_usa_el_nombre_leido_y_avisa(cliente, como_admin, catalogo):
    detalle = importar(
        cliente,
        como_admin,
        catalogo["periodo"],
        "sinqr.pdf",
        pdf_escaneado(replace(UNO, con_qr=False)),
    )
    p = pagina(cliente, como_admin, paginas(detalle)[0]["id"])
    assert p["docente"]["id"] == catalogo["uno"]  # por el nombre del encabezado
    assert p["horas_qr"] is None and p["version_documento"] is None
    assert any("código QR" in a for a in p["avisos"])


def test_pdf_danado_no_detiene_a_los_demas(cliente, como_admin, catalogo):
    detalle = importar(
        cliente,
        como_admin,
        catalogo["periodo"],
        "lote.zip",
        zip_con(
            {"bueno.pdf": pdf_escaneado(UNO), "roto.pdf": b"%PDF-1.4 esto no es un pdf valido"}
        ),
    )
    assert detalle["estado"] == "en_revision"
    estados = {d["nombre_archivo"]: d["estado"] for d in detalle["documentos"]}
    assert estados == {"bueno.pdf": "procesado", "roto.pdf": "error"}


def test_imagen_de_la_celda(cliente, como_admin, catalogo):
    detalle = importar(cliente, como_admin, catalogo["periodo"], "uno.pdf", pdf_escaneado(UNO))
    c = pagina(cliente, como_admin, paginas(detalle)[0]["id"])["celdas_detalle"][0]
    r = cliente.get(f"/importaciones/celdas/{c['id']}/imagen", headers=como_admin)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")


def test_descartar_y_cancelar(cliente, como_admin, catalogo):
    detalle = importar(
        cliente,
        como_admin,
        catalogo["periodo"],
        "lote.zip",
        zip_con({"a.pdf": pdf_escaneado(UNO), "b.pdf": pdf_escaneado(DOS)}),
    )
    a, b = (p["id"] for p in paginas(detalle))
    assert (
        cliente.post(f"/importaciones/paginas/{a}/descartar", headers=como_admin).json()["estado"]
        == "descartada"
    )
    r = cliente.post(f"/importaciones/{detalle['id']}/cancelar", headers=como_admin)
    assert r.json()["estado"] == "cancelada"
    assert pagina(cliente, como_admin, b)["estado"] == "descartada"
    # Una importación cancelada no cuenta como "ya importado".
    r = subir(cliente, como_admin, catalogo["periodo"], "a.pdf", pdf_escaneado(UNO))
    assert r.json()["estado"] == "procesando"


def test_periodo_cerrado_y_archivo_invalido(cliente, como_admin, catalogo):
    r = subir(cliente, como_admin, catalogo["periodo"], "nota.txt", b"hola")
    assert r.status_code == 415
    cliente.post(f"/periodos/{catalogo['periodo']}/cerrar", headers=como_admin)
    r = subir(cliente, como_admin, catalogo["periodo"], "uno.pdf", pdf_escaneado(UNO))
    assert r.status_code == 409 and "cerrado" in r.json()["detail"]


def test_permisos_de_importacion(cliente, como_admin, como_consulta, catalogo):
    detalle = importar(cliente, como_admin, catalogo["periodo"], "uno.pdf", pdf_escaneado(UNO))
    id_ = paginas(detalle)[0]["id"]
    assert (
        subir(
            cliente, como_consulta, catalogo["periodo"], "uno.pdf", pdf_escaneado(DOS)
        ).status_code
        == 403
    )
    for ruta in (
        "/importaciones",
        f"/importaciones/{detalle['id']}",
        f"/importaciones/paginas/{id_}",
    ):
        assert cliente.get(ruta, headers=como_consulta).status_code == 403
    r = cliente.post(f"/importaciones/paginas/{id_}/aprobar", json={}, headers=como_consulta)
    assert r.status_code == 403
    assert cliente.get("/importaciones").status_code == 401  # sin sesión
