"""Pruebas de la lógica del analizador de horarios (sin OCR ni imágenes).

Todos los datos son ficticios; imitan el formato de los horarios institucionales.
"""

from app.importers.analisis import (
    Catalogo,
    Celda,
    actividad_aproximada,
    agrupar_bloques,
    clave_equivalente,
    comparar_celdas,
    corregir_clave,
    esqueleto,
    leer_celda,
    leer_qr,
)

QR_FICTICIO = (
    "ZAPOPAN,AGOSTO - DICIEMBRE 2026,DOCENTE DE PRUEBA UNO,ZAX0001,2026-06-28,"
    "2026-07-01 AL 2026-12-31,2,0GTUT[0],TEXT[1],MAT[25],TOT[40],"
)


# --- QR ---


def test_leer_qr_extrae_encabezado_y_horas():
    e = leer_qr(QR_FICTICIO)
    assert e.docente == "DOCENTE DE PRUEBA UNO"
    assert e.periodo == "AGOSTO - DICIEMBRE 2026"
    assert e.nomina == "ZAX0001"
    assert (e.vigencia_inicio, e.vigencia_fin) == ("2026-07-01", "2026-12-31")
    assert e.version == 2
    assert e.horas["MAT"] == 25 and e.horas["TOT"] == 40 and e.horas["GTUT"] == 0


def test_leer_qr_rechaza_texto_ajeno():
    assert leer_qr("https://ejemplo.mx") is None
    assert leer_qr("A,B,C,D,E,sin vigencia,1") is None


# --- Celdas ---


def test_celda_de_clase():
    assert leer_celda("CÁLC. DIF.\nGrupo: A Aula: M01") == Celda("CÁLC. DIF.", "A", "M01")


def test_celda_de_actividad_sin_grupo_con_aula_de_dos_palabras():
    c = leer_celda("RESIDENCIA PROFESIONAL\nAula: Sala EM")
    assert c == Celda("RESIDENCIA PROFESIONAL", None, "SALA EM")


def test_celda_de_tres_lineas():
    c = leer_celda("EVENTO CIENCIA Y\nTECNOLOGIA\nGrupo: B Aula: LMAC")
    assert c == Celda("EVENTO CIENCIA Y TECNOLOGIA", "B", "LMAC")


def test_celda_con_a_acentuada_por_el_ocr():
    # El OCR en español suele leer "A" como "Á".
    assert leer_celda("MANU. AVANZ\nGrupo: Á Áula: LMAC") == Celda("MANU. AVANZ", "A", "LMAC")


def test_celda_quita_ruido_de_lineas_de_cuadricula():
    assert leer_celda("~ DINAMICA\ni Grupo: A Aula: M04") == Celda("DINAMICA", "A", "M04")


def test_firmas_y_sellos_no_se_toman_como_clase():
    assert leer_celda("Recibi original\n24/08/26") is None
    assert leer_celda("") is None


def test_corregir_clave_o_por_cero_junto_a_digitos():
    assert corregir_clave("CUBO1") == "CUB01"
    assert corregir_clave("MO4") == "M04"
    assert corregir_clave("LMAC") == "LMAC"


# --- Bloques ---


def test_agrupar_horas_consecutivas_iguales():
    celdas = {
        "lunes-7": Celda("QUIMICA", "A", "LQ"),
        "lunes-8": Celda("QUIMICA", "A", "LQ"),
        "lunes-9": Celda("QUIMICA", "B", "LQ"),  # otro grupo: bloque nuevo
        "lunes-11": Celda("QUIMICA", "B", "LQ"),  # hueco a las 10: bloque nuevo
        "martes-7": Celda("QUIMICA", "A", "LQ"),
    }
    bloques = [(b.dia, b.inicio, b.fin, b.grupo) for b in agrupar_bloques(celdas)]
    assert bloques == [
        ("lunes", 7, 9, "A"),
        ("lunes", 9, 10, "B"),
        ("lunes", 11, 12, "B"),
        ("martes", 7, 8, "A"),
    ]


# --- Comparación ---


def test_clave_equivalente_trata_o_cero_e_i_uno_como_iguales():
    assert clave_equivalente("O02") == clave_equivalente("002")
    assert clave_equivalente("I01") == clave_equivalente("101")
    assert clave_equivalente("M05") != clave_equivalente("M06")


def test_numeral_romano_distingue_materias():
    assert actividad_aproximada("Manufactura Avan I", "Manufactura Avan l")
    assert not actividad_aproximada("Manufactura Avan I", "Manufactura Avan II")
    assert not actividad_aproximada("Manufactura Avan I", "Manufactura Avan")


def test_comparar_celdas_cuenta_aciertos_faltantes_y_extras():
    esperado = {"lunes-7": Celda("DINAMICA", "A", "M04"), "lunes-8": Celda("DINAMICA", "A", "M04")}
    obtenido = {"lunes-7": Celda("DINAMICA", "A", "MO4"), "martes-9": Celda("X", "A", "M01")}
    r = comparar_celdas(esperado, obtenido)
    assert (r["posicion"].correctos, r["posicion"].total) == (1, 2)
    assert r["aula"].correctos == 0 and r["aula_equivalente"].correctos == 1
    assert r["celdas_extra"].total == 1


# --- Catálogo ---


def test_esqueleto_iguala_confusiones_tipicas():
    assert esqueleto("MOS") == esqueleto("M05")
    assert esqueleto("MOG") == esqueleto("M06")
    assert esqueleto("802") == esqueleto("B02")


def test_catalogo_verificado_corrige_confusiones():
    aulas = Catalogo(["M05", "M06", "B02", "LQ", "L4.0", "LM", "LMI"], "aula", verificado=True)
    assert aulas.corregir("MOS") == ("M05", True)
    assert aulas.corregir("M005") == ("M05", True)  # carácter duplicado
    assert aulas.corregir("802") == ("B02", True)
    assert aulas.corregir("LM") == ("LM", True)  # exacta gana aunque "LMI" se parezca


def test_catalogo_verificado_no_fusiona_entradas_parecidas():
    aulas = Catalogo(["LQ", "L4.0", "LM", "LMI"], "aula", verificado=True)
    assert len(aulas.representantes) == 4


def test_catalogo_no_corrige_si_es_ambiguo_o_desconocido():
    aulas = Catalogo(["M01", "M02"], "aula", verificado=True)
    assert aulas.corregir("ZZZ9") == ("ZZZ9", False)
    materias = Catalogo(["Manufactura Avan I", "Manufactura Avan II"], "actividad", True)
    # Sin numeral no se sabe cuál es: se deja para revisión manual.
    assert materias.corregir("Manufactura Avan") == ("Manufactura Avan", False)
    assert materias.corregir("Manufactura Avan Il") == ("Manufactura Avan II", True)


def test_catalogo_automatico_agrupa_variantes_y_elige_la_forma_de_aula():
    lecturas = ["MOS", "MOS", "MOS", "M05", "B02", "802", "B02"]
    aulas = Catalogo(lecturas, "aula")
    assert sorted(aulas.representantes) == ["B02", "M05"]
