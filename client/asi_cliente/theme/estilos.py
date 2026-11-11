"""Temas claro y oscuro. Colores sobrios, pensados para uso prolongado."""

from string import Template

PALETAS = {
    "claro": {
        "fondo": "#f5f6f8",
        "superficie": "#ffffff",
        "lateral": "#1f2a37",
        "lateral_texto": "#cbd5e1",
        "lateral_activo": "#2f3e50",
        "texto": "#1f2937",
        "texto_suave": "#6b7280",
        "borde": "#d9dde3",
        "acento": "#1d4ed8",
        "acento_texto": "#ffffff",
        "error": "#b91c1c",
        "advertencia": "#b45309",
    },
    "oscuro": {
        "fondo": "#16191d",
        "superficie": "#1f2328",
        "lateral": "#111417",
        "lateral_texto": "#aab4c0",
        "lateral_activo": "#252b33",
        "texto": "#e5e7eb",
        "texto_suave": "#9ca3af",
        "borde": "#343a42",
        "acento": "#4f83f1",
        "acento_texto": "#ffffff",
        "error": "#f87171",
        "advertencia": "#fbbf24",
    },
}

_QSS = Template("""
QWidget { background: $fondo; color: $texto; font-size: 14px; }
QLabel#titulo { font-size: 22px; font-weight: 600; }
QLabel#subtitulo, QLabel#suave { color: $texto_suave; }
QLabel#error { color: $error; }
QFrame#tarjeta { background: $superficie; border: 1px solid $borde; border-radius: 10px; }
QFrame#tarjeta QLabel, QFrame#tarjeta QCheckBox { background: transparent; }
QLineEdit {
    background: $superficie; border: 1px solid $borde; border-radius: 6px; padding: 8px;
}
QLineEdit:focus { border-color: $acento; }
QPushButton {
    background: $superficie; border: 1px solid $borde; border-radius: 6px; padding: 8px 14px;
}
QPushButton#primario { background: $acento; color: $acento_texto; border: none; font-weight: 600; }
QPushButton#primario:disabled { background: $borde; color: $texto_suave; }
QWidget#lateral { background: $lateral; }
QWidget#lateral QLabel { background: transparent; color: #ffffff; font-weight: 600; }
QListWidget#menu { background: $lateral; color: $lateral_texto; border: none; outline: none; }
QListWidget#menu::item { padding: 10px 14px; border-radius: 6px; margin: 2px 8px; }
QListWidget#menu::item:selected { background: $lateral_activo; color: #ffffff; }
QWidget#lateral QPushButton {
    background: transparent; color: $lateral_texto; border: 1px solid $lateral_activo;
}
QPushButton:disabled { color: $texto_suave; }
QLabel#advertencia { color: $advertencia; }
QTableWidget, QTableView {
    background: $superficie; alternate-background-color: $fondo; gridline-color: $borde;
    border: 1px solid $borde; border-radius: 6px;
    selection-background-color: $acento; selection-color: $acento_texto;
}
QHeaderView::section {
    background: $fondo; color: $texto_suave; border: none; border-bottom: 1px solid $borde;
    border-right: 1px solid $borde; padding: 6px; font-weight: 600;
}
QComboBox, QDateEdit, QSpinBox {
    background: $superficie; border: 1px solid $borde; border-radius: 6px; padding: 6px 8px;
}
QComboBox:focus, QDateEdit:focus, QSpinBox:focus { border-color: $acento; }
QTabWidget::pane { border: 1px solid $borde; border-radius: 6px; padding: 8px; }
QTabBar::tab {
    background: $fondo; color: $texto_suave; padding: 8px 18px; border: 1px solid $borde;
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: $superficie; color: $texto; font-weight: 600; }
QSplitter::handle { background: transparent; }
QTableWidget#cuadricula { font-size: 12px; }
""")


def hoja_de_estilo(tema: str) -> str:
    return _QSS.substitute(PALETAS[tema])
