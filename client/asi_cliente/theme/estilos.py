"""Temas claro y oscuro: identidad institucional sobria, pensada para uso prolongado.

Contraste: los textos normales cumplen al menos 4.5:1 sobre su fondo (WCAG AA) y todo
control que recibe el foco del teclado muestra un borde azul visible.
"""

from string import Template

PALETAS = {
    "claro": {
        "fondo": "#f3f5f8",
        "superficie": "#ffffff",
        "superficie_alt": "#f8fafc",
        "lateral": "#13294b",
        "lateral_texto": "#d5deeb",
        "lateral_activo": "#244575",
        "lateral_suave": "#9fb0c9",
        "menu_seleccion": "#264d8c",
        "texto": "#17202e",
        "texto_suave": "#526072",
        "borde": "#d3dae4",
        "acento": "#1b396a",
        "acento_hover": "#264d8c",
        "acento_suave": "#e7eef8",
        "acento_texto": "#ffffff",
        "foco": "#2563eb",
        "exito": "#15803d",
        "error": "#b42318",
        "error_suave": "#fdecea",
        "advertencia": "#8a5300",
        "advertencia_suave": "#fff5e0",
    },
    "oscuro": {
        "fondo": "#14181e",
        "superficie": "#1c222a",
        "superficie_alt": "#212833",
        "lateral": "#0e1622",
        "lateral_texto": "#c5d0de",
        "lateral_activo": "#22324a",
        "lateral_suave": "#8796ab",
        "menu_seleccion": "#2b4f8f",
        "texto": "#e6eaf0",
        "texto_suave": "#a3aebd",
        "borde": "#323b48",
        "acento": "#5b8def",
        "acento_hover": "#7aa3f3",
        "acento_suave": "#1f2d44",
        "acento_texto": "#0b1220",
        "foco": "#93b4f7",
        "exito": "#4ade80",
        "error": "#f87171",
        "error_suave": "#3a1f22",
        "advertencia": "#fbbf24",
        "advertencia_suave": "#3a2f17",
    },
}

_QSS = Template("""
QWidget { background: $fondo; color: $texto; font-size: 14px; }
QToolTip { background: $texto; color: $superficie; border: none; padding: 6px 8px; }

/* --- Textos --- */
QLabel#titulo { font-size: 22px; font-weight: 600; }
QLabel#titulo_seccion { font-size: 20px; font-weight: 600; background: transparent; }
QLabel#subtitulo, QLabel#suave, QLabel#ayuda { color: $texto_suave; }
QLabel#ayuda { font-size: 12px; }
QLabel#error { color: $error; }
QLabel#advertencia { color: $advertencia; }
QLabel#exito { color: $exito; }
QLabel#estado { font-weight: 600; }
QLabel#vacio {
    color: $texto_suave; background: transparent; font-size: 14px; padding: 24px;
}

/* --- Superficies --- */
QFrame#tarjeta, QFrame#panel {
    background: $superficie; border: 1px solid $borde; border-radius: 10px;
}
QFrame#tarjeta QLabel, QFrame#tarjeta QCheckBox,
QFrame#panel QLabel, QFrame#panel QCheckBox { background: transparent; }
QFrame#indicador {
    background: $superficie; border: 1px solid $borde; border-radius: 10px;
}
QFrame#indicador QLabel { background: transparent; }
QLabel#indicador_valor { font-size: 28px; font-weight: 600; }
QLabel#indicador_titulo { color: $texto_suave; font-size: 13px; }
QFrame#aviso_error { background: $error_suave; border-radius: 8px; }
QFrame#aviso_advertencia { background: $advertencia_suave; border-radius: 8px; }
QFrame#aviso_error QLabel, QFrame#aviso_advertencia QLabel { background: transparent; }

/* --- Franja del servidor: siempre visible, color según el tipo --- */
QLabel#franja_servidor {
    color: #ffffff; font-weight: 700; font-size: 13px; padding: 6px 16px;
    letter-spacing: 0.3px;
}
QLabel#franja_servidor[tipo="institucional"] { background: #166534; }
QLabel#franja_servidor[tipo="demostracion"] { background: #9a3412; }
QLabel#franja_servidor[tipo="revision"] { background: #6d28d9; }
QLabel#franja_servidor[tipo="desarrollo"] { background: #1e40af; }
QLabel#franja_servidor[tipo="desconocido"] { background: #374151; }
QLabel#franja_servidor[tipo="local"] { background: #0f766e; }

/* --- Barra superior y menú lateral --- */
QWidget#barra_superior { background: $superficie; border-bottom: 1px solid $borde; }
QWidget#barra_superior QLabel { background: transparent; }
QLabel#chip_periodo {
    background: $acento_suave; color: $acento; border-radius: 12px; padding: 4px 12px;
    font-weight: 600;
}
QLabel#chip_alerta {
    background: $advertencia_suave; color: $advertencia; border-radius: 12px;
    padding: 4px 12px; font-weight: 600;
}
QWidget#lateral { background: $lateral; }
QWidget#lateral QLabel { background: transparent; color: #ffffff; }
QLabel#marca { font-size: 17px; font-weight: 700; letter-spacing: 0.5px; }
QLabel#marca_sub { color: $lateral_suave; font-size: 11px; }
QLabel#usuario_lateral { color: $lateral_texto; font-size: 13px; }
QListWidget#menu {
    background: $lateral; color: $lateral_texto; border: none; outline: none; font-size: 15px;
}
QListWidget#menu::item { padding: 11px 12px; border-radius: 8px; margin: 2px 10px; }
QListWidget#menu::item:hover { background: $lateral_activo; }
QListWidget#menu::item:selected { background: $menu_seleccion; color: #ffffff; font-weight: 600; }
QListWidget#menu:focus { border: none; }
QWidget#lateral QPushButton {
    background: transparent; color: $lateral_texto; border: 1px solid $lateral_activo;
    text-align: left; padding: 8px 12px;
}
QWidget#lateral QPushButton:hover { background: $lateral_activo; }
QWidget#lateral QPushButton:focus { border: 2px solid $foco; }

/* --- Botones --- */
QPushButton, QToolButton {
    background: $superficie; color: $texto; border: 1px solid $borde; border-radius: 6px;
    padding: 8px 14px;
}
QPushButton:hover, QToolButton:hover { border-color: $acento; background: $acento_suave; }
QPushButton:focus, QToolButton:focus { border: 2px solid $foco; }
QPushButton:disabled { color: $texto_suave; background: $fondo; border-color: $borde; }
QPushButton#primario {
    background: $acento; color: $acento_texto; border: 1px solid $acento; font-weight: 600;
}
QPushButton#primario:hover { background: $acento_hover; border-color: $acento_hover; }
QPushButton#primario:focus { border: 2px solid $foco; }
QPushButton#primario:disabled { background: $borde; color: $texto_suave; border-color: $borde; }
QPushButton#peligro { color: $error; border-color: $error; }
QPushButton#enlace {
    background: transparent; border: none; color: $acento; text-decoration: underline;
}
QPushButton#peligro:hover { background: $error_suave; }
QPushButton#acceso {
    text-align: left; padding: 14px 16px; font-size: 15px; font-weight: 600;
    background: $superficie;
}
QToolButton#desplegable {
    border: none; background: transparent; color: $acento; font-weight: 600; padding: 4px 2px;
}
QToolButton#desplegable:hover { text-decoration: underline; background: transparent; }

/* --- Campos --- */
QLineEdit, QComboBox, QDateEdit, QSpinBox, QTimeEdit, QPlainTextEdit, QTextEdit {
    background: $superficie; border: 1px solid $borde; border-radius: 6px; padding: 7px 8px;
    selection-background-color: $acento; selection-color: $acento_texto;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QTimeEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 2px solid $foco; }
QComboBox QAbstractItemView {
    background: $superficie; border: 1px solid $borde;
    selection-background-color: $acento; selection-color: $acento_texto;
}
QCheckBox, QRadioButton { background: transparent; spacing: 8px; }
QRadioButton::indicator {
    width: 14px; height: 14px; border-radius: 9px; border: 2px solid $texto_suave;
    background: $superficie;
}
QRadioButton::indicator:hover { border-color: $acento; }
QRadioButton::indicator:checked { border: 5px solid $acento; width: 8px; height: 8px; }
QRadioButton:focus, QCheckBox:focus { color: $acento; }

/* --- Tablas --- */
QTableWidget, QTableView, QListWidget {
    background: $superficie; alternate-background-color: $superficie_alt;
    gridline-color: $borde; border: 1px solid $borde; border-radius: 8px;
    selection-background-color: $acento; selection-color: $acento_texto;
}
QTableWidget:focus, QTableView:focus { border: 2px solid $foco; }
QHeaderView::section {
    background: $superficie_alt; color: $texto_suave; border: none;
    border-bottom: 1px solid $borde; border-right: 1px solid $borde; padding: 8px 6px;
    font-weight: 600;
}
QTableWidget#cuadricula { font-size: 12px; }
/* Horas de la cuadrícula: poco margen, para poder compactar las horas vacías. */
QTableWidget#cuadricula QHeaderView::section:vertical { padding: 2px 8px; }

/* --- Asistencia por hora: registro rápido --- */
QFrame#fila_asistencia {
    background: $superficie; border: 1px solid $borde; border-radius: 10px;
    border-left: 6px solid #94a3b8;
}
QFrame#fila_asistencia QLabel { background: transparent; }
QFrame#fila_asistencia[estado="asistio"] { border-left-color: #15803d; }
QFrame#fila_asistencia[estado="retardo"] { border-left-color: #b45309; }
QFrame#fila_asistencia[estado="falto"] { border-left-color: #b91c1c; }
QFrame#fila_asistencia[estado="justificado"] { border-left-color: #1d4ed8; }
QFrame#fila_asistencia[estado="parcial"] { border-left-color: #7c3aed; }
QLabel#fila_hora { font-size: 16px; font-weight: 700; color: $texto; }
QLabel#fila_docente { font-size: 15px; font-weight: 600; }
QLabel#fila_detalle { color: $texto_suave; font-size: 13px; }
QLabel#fila_instruccion { font-weight: 600; }
QLabel#fila_aviso { font-size: 13px; }
QLabel#fila_aviso[tipo="exito"] { color: $exito; font-weight: 600; }
QLabel#fila_aviso[tipo="error"] { color: $error; font-weight: 600; }
QLabel#fila_aviso[tipo="informacion"] { color: $texto_suave; }
QFrame#fila_asistencia QLabel#chip_estado {
    border-radius: 12px; padding: 4px 10px; font-weight: 700; font-size: 13px;
    color: #ffffff; background: #64748b;
}
QFrame#fila_asistencia QLabel#chip_estado[estado="asistio"] { background: #15803d; }
QFrame#fila_asistencia QLabel#chip_estado[estado="retardo"] { background: #b45309; }
QFrame#fila_asistencia QLabel#chip_estado[estado="falto"] { background: #b91c1c; }
QFrame#fila_asistencia QLabel#chip_estado[estado="justificado"] { background: #1d4ed8; }
QFrame#fila_asistencia QLabel#chip_estado[estado="parcial"] { background: #7c3aed; }
QFrame#fila_asistencia QLabel#chip_estado[estado="inhabil"] { background: #6b7280; }
QPushButton#btn_asistio, QPushButton#btn_retardo, QPushButton#btn_falto,
QPushButton#btn_justificado {
    background: $superficie; border-width: 2px; border-style: solid; border-radius: 8px;
    font-weight: 700; font-size: 14px; padding: 6px 14px;
}
QPushButton#btn_asistio { color: #15803d; border-color: #15803d; }
QPushButton#btn_retardo { color: #b45309; border-color: #b45309; }
QPushButton#btn_falto { color: #b91c1c; border-color: #b91c1c; }
QPushButton#btn_justificado { color: #1d4ed8; border-color: #1d4ed8; }
QPushButton#btn_asistio:hover { background: #dcfce7; }
QPushButton#btn_retardo:hover { background: #fef3c7; }
QPushButton#btn_falto:hover { background: #fee2e2; }
QPushButton#btn_justificado:hover { background: #dbeafe; }
QPushButton#btn_asistio:checked { background: #15803d; color: #ffffff; }
QPushButton#btn_retardo:checked { background: #b45309; color: #ffffff; }
QPushButton#btn_falto:checked { background: #b91c1c; color: #ffffff; }
QPushButton#btn_justificado:checked { background: #1d4ed8; color: #ffffff; }
QPushButton#btn_asistio:disabled, QPushButton#btn_retardo:disabled,
QPushButton#btn_falto:disabled, QPushButton#btn_justificado:disabled {
    color: $texto_suave; border-color: $borde; background: $fondo;
}
QPushButton#btn_asistio:checked:disabled { background: #15803d; color: #ffffff; }
QPushButton#btn_retardo:checked:disabled { background: #b45309; color: #ffffff; }
QPushButton#btn_falto:checked:disabled { background: #b91c1c; color: #ffffff; }
QPushButton#btn_justificado:checked:disabled { background: #1d4ed8; color: #ffffff; }
QPushButton#btn_asistio:focus, QPushButton#btn_retardo:focus, QPushButton#btn_falto:focus,
QPushButton#btn_justificado:focus { border: 3px solid $foco; }
QPushButton#btn_secundario { padding: 6px 10px; font-size: 13px; }
QLabel#indicador_valor[tono="cumplidas"] { color: $exito; }
QLabel#indicador_valor[tono="retardo"] { color: #b45309; }
QLabel#indicador_valor[tono="falto"] { color: $error; }
QLabel#indicador_valor[tono="pendiente"] { color: $texto_suave; }
QWidget#lista_asistencia { background: transparent; }

/* --- Pestañas (subsecciones) --- */
QTabWidget::pane { border: none; border-top: 1px solid $borde; padding-top: 12px; }
QTabWidget#subsecciones::pane { padding-top: 16px; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent; color: $texto_suave; padding: 10px 16px; margin-right: 4px;
    border: none; border-bottom: 3px solid transparent; font-weight: 600;
}
QTabBar::tab:hover { color: $texto; }
QTabBar::tab:selected { color: $acento; border-bottom: 3px solid $acento; }
QTabBar::tab:focus { color: $acento; }

/* --- Asistente --- */
QLabel#paso { color: $texto_suave; padding: 6px 10px; font-weight: 600; }
QLabel#paso_actual {
    color: $acento_texto; background: $acento; border-radius: 12px; padding: 6px 12px;
    font-weight: 600;
}
QLabel#paso_hecho { color: $exito; padding: 6px 10px; font-weight: 600; }

QSplitter::handle { background: transparent; }
QScrollArea { border: none; }
""")


def hoja_de_estilo(tema: str) -> str:
    return _QSS.substitute(PALETAS[tema])


def color(tema: str, clave: str) -> str:
    return PALETAS.get(tema, PALETAS["claro"])[clave]
