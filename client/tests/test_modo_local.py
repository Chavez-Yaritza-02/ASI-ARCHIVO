"""Aplicación local (etapa 3): arranque sin servidor ni internet, cuenta única, cierre y
reapertura sin pérdida. Datos ficticios en carpetas temporales; nunca la carpeta real."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QMessageBox

from asi_cliente import local
from asi_cliente.servidor import describir_servidor
from asi_cliente.views import cuenta_local
from asi_cliente.views.login import VentanaLogin

ESCENARIO = Path(__file__).with_name("escenario_local.py")


def escenario(carpeta: Path, fase: str) -> dict:
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("ASI_", "PG"))}
    entorno["QT_QPA_PLATFORM"] = "offscreen"
    r = subprocess.run(
        [sys.executable, str(ESCENARIO), str(carpeta), fase],
        env=entorno,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_registrar_cerrar_y_volver_a_abrir_sin_red_ni_servidor(tmp_path):
    carpeta = tmp_path / "ASI-ARCHIVO"
    primera = escenario(carpeta, "primera")
    assert primera["creada"] is True
    assert primera["estado_inicial"] == {"configurada": False, "usuario": None}
    assert primera["registro"] == "asistio"
    assert primera["estados"] == ["asistio", "falto"]
    assert primera["duplicado"] == 409
    assert primera["identidad"] == "local" and primera["sistema"] == "ok"

    # Otro proceso: como cerrar la aplicación y volver a abrirla.
    segunda = escenario(carpeta, "segunda")
    assert segunda["creada"] is False
    assert segunda["estado_inicial"] == {"configurada": True, "usuario": "jefatura"}
    assert segunda["estados"] == ["asistio", "falto"]
    assert segunda["duplicado"] == 409

    # Lo guardado está en el archivo SQLite de la carpeta de datos.
    base = carpeta / "datos" / "asi-archivo.db"
    assert Path(segunda["base"]) == base.resolve()
    with sqlite3.connect(base) as c:
        assert c.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert c.execute(
            "SELECT estado FROM asistencia_hora ORDER BY programado_inicio"
        ).fetchall() == [
            ("asistio",),
            ("falto",),
        ]
        assert c.execute("SELECT count(*) FROM usuario").fetchone() == (1,)
        acciones = {a for (a,) in c.execute("SELECT accion FROM auditoria")}
        assert {"crear", "login"} <= acciones
        assert c.execute("SELECT count(*) FROM cuenta_recuperacion").fetchone() == (1,)
    assert (
        not (carpeta / "datos" / "asi-archivo.db-wal").exists()
        or (carpeta / "datos" / "asi-archivo.db-wal").stat().st_size == 0
    )


def test_no_se_abren_dos_ventanas_sobre_la_misma_base(tmp_path):
    otra = QLockFile(str(tmp_path / "asi-archivo.lock"))
    assert otra.tryLock(100)
    try:
        with pytest.raises(local.ErrorLocal, match="ya está abierto"):
            local._bloquear(tmp_path)
    finally:
        otra.unlock()
    bloqueo = local._bloquear(tmp_path)  # al cerrarse la otra, ya se puede
    bloqueo.unlock()


def test_carpeta_de_datos_fuera_del_programa(monkeypatch, tmp_path):
    monkeypatch.delenv("ASI_DATOS_LOCALES", raising=False)
    monkeypatch.setattr(local.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert local.carpeta_datos() == tmp_path / "AppData" / "Local" / "ASI-ARCHIVO"
    monkeypatch.setenv("ASI_DATOS_LOCALES", str(tmp_path / "ensayo"))
    assert local.carpeta_datos() == tmp_path / "ensayo"


def test_franja_dice_esta_computadora():
    s = describir_servidor("http://esta-computadora", {"tipo_servidor": "local"})
    assert s.texto == "ESTA COMPUTADORA · datos guardados en este equipo, sin internet"


# --- ventanas de la cuenta ------------------------------------------------------------------


class ApiFalsa:
    es_local = True
    carpeta_local = Path("/tmp/ficticia")
    usuario = None

    def __init__(self, respuesta=None):
        self.enviado = []
        self.respuesta = respuesta or {}

    def post(self, ruta, datos=None):
        self.enviado.append((ruta, datos))
        return self.respuesta


def test_contrasena_corta_o_distinta_no_se_envia(qtbot):
    api = ApiFalsa()
    d = cuenta_local.DialogoPrimeraEjecucion(api)
    qtbot.addWidget(d)
    d.campo_usuario.setText("jefatura")
    d.campo_nombre.setText("Jefatura")
    d.campo_clave.setText("corta")
    d.campo_confirmar.setText("corta")
    assert not d.crear() and "al menos 10" in d.mensaje.text()
    d.campo_clave.setText("clave-ficticia-01")
    d.campo_confirmar.setText("clave-ficticia-02")
    assert not d.crear() and "no coinciden" in d.mensaje.text()
    assert api.enviado == []


def test_codigo_no_se_cierra_sin_confirmar_y_kit_pdf(qtbot, tmp_path, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a))
    d = cuenta_local.DialogoCodigoRecuperacion("jefatura", "ABCDE-FGHJK-MNPQR-STVWX-YZ012", "x")
    qtbot.addWidget(d)
    d.show()
    assert not d.continuar.isEnabled()
    d.reject()  # Esc: no se cierra sin confirmar
    assert d.isVisible() and len(avisos) == 1
    kit = tmp_path / "kit.pdf"
    d.guardar_kit(str(kit))
    assert kit.read_bytes().startswith(b"%PDF") and d.kit_guardado == kit
    d.confirmar.setChecked(True)
    assert d.continuar.isEnabled()
    d.continuar.click()
    assert d.result() == d.DialogCode.Accepted


def test_kit_explica_como_usar_y_guardar_el_codigo():
    html = cuenta_local.html_kit("jefatura", "ABCDE-FGHJK", __import__("datetime").datetime.now())
    assert "ABCDE-FGHJK" in html and "fuera de esta computadora" in html
    assert "contraseña" in html.lower()


def test_login_local_ofrece_recuperar_y_no_cambiar_servidor(qtbot):
    v = VentanaLogin(ApiFalsa(), "jefatura")
    qtbot.addWidget(v)
    assert v.boton_servidor.isHidden() and not v.boton_olvido.isHidden()
    assert v.correo.placeholderText() == "Usuario"


def test_primera_ejecucion_envia_la_cuenta_y_muestra_el_codigo(qtbot, monkeypatch):
    mostrados = []
    monkeypatch.setattr(
        cuenta_local.DialogoPrimeraEjecucion, "mostrar_codigo", lambda s: mostrados.append(s.codigo)
    )
    api = ApiFalsa({"usuario": "jefatura", "codigo_recuperacion": "ABCDE-FGHJK-MNPQR-STVWX-YZ012"})
    d = cuenta_local.DialogoPrimeraEjecucion(api)
    qtbot.addWidget(d)
    d.campo_usuario.setText("Jefatura")
    d.campo_nombre.setText("Jefatura Ficticia")
    d.campo_clave.setText("clave-ficticia-01")
    d.campo_confirmar.setText("clave-ficticia-01")
    assert d.crear()
    assert api.enviado[0][0] == "/local/cuenta"
    assert mostrados == ["ABCDE-FGHJK-MNPQR-STVWX-YZ012"]
    assert d.campo_clave.text() == ""  # la contraseña no se queda en la ventana
