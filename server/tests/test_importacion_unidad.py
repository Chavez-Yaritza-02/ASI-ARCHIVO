"""Comparación con catálogos y lectura de archivos (sin base de datos ni OCR)."""

import io
import zipfile

import pytest

from app.importers.coincidencias import (
    COINCIDE,
    SIN_COINCIDENCIA,
    SUGERIDO,
    VACIO,
    buscar_asignatura,
    buscar_aula,
    buscar_docente,
)
from app.services import importacion
from app.services.comun import ErrorNegocio

AULAS = [(1, "M05"), (2, "M06"), (3, "LQ"), (4, "SALA EM"), (5, "B02")]
ASIGNATURAS = [
    (1, "CÁLC. DIF."),
    (2, "Manufactura Avan I"),
    (3, "Manufactura Avan II"),
    (4, "MEC. DE MATER"),
    (5, "MEC. DE MATERIA"),
]
DOCENTES = [(1, "DOCENTE PRUEBA UNO", "ZZX0001"), (2, "DOCENTE PRUEBA DOS", None)]


# --- Aulas ---


def test_aula_identica_coincide_aunque_cambien_mayusculas_y_espacios():
    assert buscar_aula("sala  em", AULAS).__dict__ == {
        "id": 4,
        "estado": COINCIDE,
        "candidatos": [],
    }


def test_aula_con_confusion_tipica_queda_solo_como_sugerencia():
    assert (buscar_aula("MOS", AULAS).id, buscar_aula("MOS", AULAS).estado) == (1, SUGERIDO)
    assert buscar_aula("802", AULAS).estado == SUGERIDO  # B02
    assert buscar_aula("LO", AULAS).id == 3  # LQ leída como LO
    assert buscar_aula("M005", AULAS).id == 1  # carácter duplicado


def test_aula_desconocida_o_vacia():
    assert buscar_aula("ZZ9", AULAS).estado == SIN_COINCIDENCIA
    assert buscar_aula(None, AULAS).estado == VACIO


def test_aula_ambigua_no_se_asigna():
    r = buscar_aula("MO", [(1, "M01"), (2, "M02")])
    assert r.id is None and r.estado == SIN_COINCIDENCIA


# --- Asignaturas ---


def test_asignatura_sin_acentos_ni_puntos_coincide():
    assert buscar_asignatura("CALC DIF", ASIGNATURAS).estado == COINCIDE


def test_asignatura_parecida_es_sugerencia_pero_respeta_numeral():
    r = buscar_asignatura("Manufactura Avan Il", ASIGNATURAS)
    assert (r.id, r.estado) == (3, SUGERIDO)
    # Sin numeral no se sabe si es I o II: no se asigna.
    assert buscar_asignatura("Manufactura Avan", ASIGNATURAS).id is None


def test_materias_distintas_parecidas_no_se_confunden():
    assert buscar_asignatura("MEC. DE MATER", ASIGNATURAS).id == 4
    assert buscar_asignatura("MEC. DE MATERIA", ASIGNATURAS).id == 5


# --- Docentes ---


def test_docente_por_nomina_nombre_o_sugerencia():
    assert buscar_docente("OTRO NOMBRE", "zzx0001", DOCENTES).__dict__["id"] == 1
    assert buscar_docente("docente prueba dos", None, DOCENTES).estado == COINCIDE
    r = buscar_docente("DOCENTE PRUEBA D0S", None, DOCENTES)
    assert (r.id, r.estado) == (2, SUGERIDO)
    assert buscar_docente("NADIE", None, DOCENTES).estado == SIN_COINCIDENCIA


# --- Archivos ---


def _zip(entradas: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, datos in entradas.items():
            zf.writestr(nombre, datos)
    return buf.getvalue()


def test_pdf_suelto_y_zip_ignorando_rutas_y_otros_archivos():
    assert importacion.extraer_pdfs("x.pdf", b"%PDF-1.4 ...") == [("x.pdf", b"%PDF-1.4 ...")]
    contenido = _zip(
        {
            "../../fuera.pdf": b"%PDF-a",
            "carpeta/dentro.pdf": b"%PDF-b",
            "LISTA.txt": b"texto",
            "falso.pdf": b"no soy pdf",
            "__MACOSX/._oculto.pdf": b"%PDF-c",
        }
    )
    assert importacion.extraer_pdfs("h.zip", contenido) == [
        ("dentro.pdf", b"%PDF-b"),
        ("fuera.pdf", b"%PDF-a"),
    ]


def test_archivos_invalidos(monkeypatch):
    with pytest.raises(ErrorNegocio) as e:
        importacion.extraer_pdfs("x.docx", b"PK no es zip")
    assert e.value.estado_http == 415
    with pytest.raises(ErrorNegocio) as e:
        importacion.extraer_pdfs("x.zip", _zip({"a.txt": b"hola"}))
    assert e.value.estado_http == 422
    monkeypatch.setattr(importacion, "TAMANO_MAXIMO", 10)
    with pytest.raises(ErrorNegocio) as e:
        importacion.extraer_pdfs("x.pdf", b"%PDF-" + b"0" * 20)
    assert e.value.estado_http == 413


def test_zip_que_se_infla_demasiado_se_rechaza(monkeypatch):
    monkeypatch.setattr(importacion, "TAMANO_MAXIMO_DESCOMPRIMIDO", 100)
    with pytest.raises(ErrorNegocio) as e:
        importacion.extraer_pdfs("x.zip", _zip({"a.pdf": b"%PDF-" + b"0" * 500}))
    assert e.value.estado_http == 413


def test_letra_de_grupo_corrige_digitos_parecidos():
    assert importacion.letra_de_grupo("0") == "O"
    assert importacion.letra_de_grupo(" 8 ") == "B"
    assert importacion.letra_de_grupo("a") == "A"
    assert importacion.letra_de_grupo("") is None
