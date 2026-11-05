"""Prueba de aceptación de ASI-ARCHIVO contra un servidor instalado (HTTPS real).

Recorre lo que usará la Jefatura, con DATOS FICTICIOS:
  1. Identidad y estado del servidor (base, esquema, antivirus).
  2. Iniciar sesión (administrador y consulta) y permisos.
  3. Docentes y catálogos.
  4. Importar un horario en PDF escaneado (OCR) y corregir lo que el OCR no reconoció.
  5. Aprobar, confirmar y fijar la vigencia del horario.
  6. Registrar asistencia por hora (asistió, falta, retardo).
  7. Reportes PDF y Excel (día y rango).
  8. Documentos: cargar (pasa por el antivirus), consultar y descargar el original.

Uso (SOLO en un servidor de prueba RECIÉN INSTALADO con ASI_INSTANCIA_ACEPTACION=true;
se niega a correr si el servidor no está marcado así o si ya tiene datos):
  uv run python herramientas/aceptacion_servidor.py --url https://localhost:8443 \\
      --certificado servidor/certificado/ASI-ARCHIVO-raiz.crt \\
      --admin admin@prueba.local --consulta consulta@prueba.local --confirmo-servidor-de-prueba
Las contraseñas se piden en pantalla (o por la entrada estándar, una por línea).
"""

import argparse
import getpass
import hashlib
import io
import json
import ssl
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import pymupdf
from openpyxl import load_workbook

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "server" / "tests"))
from horario_ficticio import UNO, pdf_escaneado  # noqa: E402

from asi_cliente.api.cliente import ClienteApi, ErrorApi, validar_url  # noqa: E402

LUNES = date(2026, 11, 2)
resultados: list[tuple[str, bool, str]] = []


def paso(nombre: str, ok: bool, detalle: str = "") -> None:
    resultados.append((nombre, ok, detalle))
    print(f"[{'OK' if ok else 'FALLA'}] {nombre}" + (f" — {detalle}" if detalle else ""))
    if not ok:
        raise SystemExit(1)


def cliente(url: str, certificado: str | None) -> ClienteApi:
    verificar = ssl.create_default_context(cafile=certificado)
    return ClienteApi(
        http=httpx.Client(
            base_url=validar_url(url, solo_https=True),
            verify=verificar,
            timeout=120,
            trust_env=False,
        )
    )


def pdf_ficticio() -> bytes:
    doc = pymupdf.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 72), "Justificante FICTICIO para la prueba de aceptación")
    return doc.tobytes()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--certificado")
    p.add_argument("--admin", required=True)
    p.add_argument("--consulta", required=True)
    p.add_argument("--confirmo-servidor-de-prueba", action="store_true")
    a = p.parse_args()
    if not a.confirmo_servidor_de_prueba:
        sys.exit("Solo para servidores de prueba: agrega --confirmo-servidor-de-prueba")
    leer = (
        (lambda _: sys.stdin.readline().rstrip("\n"))
        if not sys.stdin.isatty()
        else (getpass.getpass)
    )
    clave_admin = leer(f"Contraseña de {a.admin}: ")
    clave_consulta = leer(f"Contraseña de {a.consulta}: ")

    api = cliente(a.url, a.certificado)
    ident = api.get("/sistema/identidad")
    paso("Servidor HTTPS identificado", ident["producto"] == "ASI-ARCHIVO", ident["version"])
    if ident.get("aceptacion_ficticia") is not True:
        sys.exit("Servidor no marcado para aceptación ficticia: no se modifica ningún dato")
    usuario = api.iniciar_sesion(a.admin, clave_admin)
    paso("Inicio de sesión del administrador", "administrador" in usuario.roles)
    if api.get("/docentes") or api.get("/periodos") or api.get("/documentos")["total"]:
        sys.exit("La instancia de aceptación debe estar vacía: no se modifican datos existentes")
    estado = api.get("/sistema/estado")
    paso(
        "Base de datos y esquema",
        estado["base_de_datos"] == "ok" and estado["esquema"] == "compatible",
    )
    paso("Antivirus configurado en el servidor", estado["antivirus_configurado"] is True)

    # --- Docentes, periodo y catálogos (ficticios) ---
    if not any(p["nombre"] == "AGOSTO - DICIEMBRE 2026" for p in api.get("/periodos")):
        periodo = api.post(
            "/periodos",
            {
                "nombre": "Agosto - Diciembre 2026",
                "fecha_inicio": "2026-08-01",
                "fecha_fin": "2026-12-31",
            },
        )
        api.post(f"/periodos/{periodo['id']}/activar")
    periodo = next(p for p in api.get("/periodos") if p["nombre"] == "AGOSTO - DICIEMBRE 2026")
    for ruta, datos in (
        ("/docentes", {"nombre": UNO.docente, "nomina": UNO.nomina}),
        ("/asignaturas", {"nombre": "CÁLC. DIF."}),
        ("/asignaturas", {"nombre": "GESTIÓN ACADÉMICA", "tipo": "actividad"}),
        ("/aulas", {"clave": "M01"}),
        ("/aulas", {"clave": "Sala EM"}),
    ):
        try:
            api.post(ruta, datos)
        except ErrorApi as e:
            if e.estado != 409:
                raise
    docentes = api.get("/docentes", buscar="DOCENTE PRUEBA UNO")
    paso("Consultar docentes", len(docentes) == 1, docentes[0]["nombre"])

    # --- Importar horario escaneado y corregir el OCR ---
    lote = api.subir(
        "/importaciones",
        "horario_ficticio.pdf",
        pdf_escaneado(UNO),
        {"periodo_id": str(periodo["id"])},
    )
    for _ in range(120):
        lote = api.get(f"/importaciones/{lote['id']}")
        if lote["estado"] != "procesando":
            break
        time.sleep(1)
    paginas = [pg for d in lote["documentos"] for pg in d["paginas"]]
    paso(
        "Importar PDF escaneado (OCR en el servidor)",
        lote["estado"] == "en_revision" and len(paginas) == 1,
        f"{lote['procesados']} PDF procesado",
    )
    pagina = api.get(f"/importaciones/paginas/{paginas[0]['id']}")
    faltantes = [c for c in pagina["celdas_detalle"] if c["asignatura_id"] is None]
    paso(
        "El OCR leyó las 5 horas y marcó lo que no reconoce",
        len(pagina["celdas_detalle"]) == 5 and len(faltantes) == 2,
        f"sin coincidencia: {', '.join(c['actividad_texto'] for c in faltantes)}",
    )
    nuevas = {}
    for c in faltantes:  # el usuario crea las materias que faltaban
        tipo = "actividad" if c["grupo_letra"] is None else "materia"
        try:
            nuevas[c["actividad_texto"]] = api.post(
                "/asignaturas", {"nombre": c["actividad_texto"], "tipo": tipo}
            )["id"]
        except ErrorApi:
            nuevas[c["actividad_texto"]] = api.get("/asignaturas", buscar=c["actividad_texto"])[0][
                "id"
            ]
    aulas = {x["clave"]: x["id"] for x in api.get("/aulas")}
    for clave in ("M05", "DOM-03"):
        if clave not in aulas:
            aulas[clave] = api.post("/aulas", {"clave": clave})["id"]
    celdas = [
        {
            "id": c["id"],
            "dia": c["dia"],
            "hora": c["hora"],
            "asignatura_id": c["asignatura_id"] or nuevas[c["actividad_texto"]],
            "aula_id": c["aula_id"] or aulas.get(c["aula_texto"]),
            "grupo_id": None,
            "grupo_letra": c["grupo_letra"],
            "confirmar": True,
        }
        for c in pagina["celdas_detalle"]
    ]
    pagina = api.put(f"/importaciones/paginas/{pagina['id']}", {"celdas": celdas})
    pagina = api.post(f"/importaciones/paginas/{pagina['id']}/aceptar-sugerencias")
    paso("Corregir errores del OCR en la revisión", pagina["lista_pendientes"] == [])
    horario = api.post(f"/importaciones/paginas/{pagina['id']}/aprobar", {})
    paso("Aprobar: se crea un borrador", horario["estado"] == "borrador", f"{horario['horas']} h")
    horario = api.post(f"/horarios/{horario['id']}/confirmar", {"aceptar_advertencias": True})
    horario = api.post(
        f"/horarios/{horario['id']}/vigencia",
        {"desde": "2026-08-17", "motivo": "Prueba de aceptación (ficticio)"},
    )
    paso("Confirmar horario y su vigencia", horario["estado"] == "vigente")

    # --- Asistencia por hora ---
    dia = api.get("/bitacora/horas", fecha=LUNES.isoformat(), docente_id=docentes[0]["id"])
    filas = dia["filas"]
    paso("Horas programadas del lunes", len(filas) == 3, f"{len(filas)} horas")
    estados = [("asistio", {}), ("falto", {}), ("retardo", {"hora_entrada": "09:15:00"})]
    for fila, (estado_hora, extra) in zip(filas, estados, strict=True):
        if fila.get("asistencia") or fila.get("registro"):
            continue
        api.post(
            "/asistencias/horas",
            {
                "docente_id": fila["docente_id"],
                "fecha": LUNES.isoformat(),
                "bloque_id": fila["bloque_id"],
                "programado_inicio": fila["programado_inicio"],
                "estado": estado_hora,
                **extra,
            },
        )
    dia = api.get("/bitacora/horas", fecha=LUNES.isoformat(), docente_id=docentes[0]["id"])
    minutos = dia["totales"]["minutos"]
    paso(
        "Registrar asistencia por hora",
        minutos["pendientes"] == 0,
        f"cumplidos {minutos['cumplidas']} min, faltantes {minutos['faltantes']} min",
    )

    # --- Reportes ---
    consulta = f"fecha={LUNES.isoformat()}"
    pdf = api.obtener_bytes(f"/bitacora/horas/exportar?{consulta}&formato=pdf")
    xlsx = api.obtener_bytes(f"/bitacora/horas/exportar?{consulta}&formato=xlsx")
    rango = api.obtener_bytes(
        "/bitacora/horas/reporte?desde=2026-11-02&hasta=2026-11-06&formato=xlsx"
    )
    libro = load_workbook(io.BytesIO(xlsx))
    paso("Reporte PDF", bool(pdf) and pdf.startswith(b"%PDF"), f"{len(pdf)} bytes")
    paso(
        "Reporte Excel (día y rango)",
        bool(rango) and len(libro.sheetnames) >= 1,
        ", ".join(libro.sheetnames),
    )

    # --- Documentos ---
    categorias = api.get("/documentos/categorias")
    justificante = next(c for c in categorias if "justific" in c["nombre"].lower())
    contenido = pdf_ficticio()
    doc = api.subir(
        "/documentos",
        "justificante_ficticio.pdf",
        contenido,
        {
            "datos": json.dumps(
                {
                    "nombre": "Justificante ficticio",
                    "fecha": LUNES.isoformat(),
                    "categoria_id": justificante["id"],
                    "docente_id": docentes[0]["id"],
                }
            )
        },
    )
    paso("Cargar documento (revisado por el antivirus)", bool(doc.get("documento_id")))
    doc_id = doc["documento_id"]
    detalle = api.get(f"/documentos/{doc_id}")
    version = detalle["versiones"][0]
    original = api.obtener_bytes(f"/documentos/{doc_id}/versiones/{version['id']}/descargar")
    paso(
        "Descargar documento autorizado",
        hashlib.sha256(original or b"").hexdigest() == hashlib.sha256(contenido).hexdigest(),
        "huella SHA-256 idéntica",
    )

    # --- Rol consulta ---
    lector = cliente(a.url, a.certificado)
    lector.iniciar_sesion(a.consulta, clave_consulta)
    puede_ver = bool(lector.get("/bitacora/horas", fecha=LUNES.isoformat()))
    try:
        lector.post("/docentes", {"nombre": "NO DEBE CREARSE"})
        bloqueado = False
    except ErrorApi as e:
        bloqueado = e.estado == 403
    paso("Rol consulta: ve pero no modifica", puede_ver and bloqueado)
    print(f"\nACEPTACIÓN COMPLETA: {len(resultados)} comprobaciones aprobadas")


if __name__ == "__main__":
    main()
