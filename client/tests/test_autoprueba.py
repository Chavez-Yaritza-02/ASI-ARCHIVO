"""La autoprueba del instalador de Windows también se ejecuta en cada corrida local."""

import json
import sys

from PySide6.QtWidgets import QApplication

from asi_cliente import autoprueba


def test_autoprueba_del_ejecutable(qtbot, tmp_path, monkeypatch):
    destino = tmp_path / "autoprueba.json"
    monkeypatch.setattr(sys, "argv", ["asi-archivo", "--autoprueba", "--resultado", str(destino)])
    codigo = autoprueba.ejecutar(QApplication.instance())
    datos = json.loads(destino.read_text())
    assert codigo in (0, None) and datos["estado"] == "ok"
    assert datos["login"] and datos["permisos"] and datos["exportacion"]
