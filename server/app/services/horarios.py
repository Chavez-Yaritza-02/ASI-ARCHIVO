"""Reglas de negocio de los horarios versionados.

Ciclo de vida de una versión (ver app/models/horarios.py):

    borrador --(confirmar)--> vigente --(otra versión confirmada)--> historico
    borrador --(descartar)--> descartado

Validaciones:
- Errores (impiden guardar): bloques del mismo horario que se traslapan o se
  repiten, horas inválidas, catálogos inexistentes o inactivos, materia sin grupo.
- Advertencias (piden confirmación explícita al confirmar): el aula ya está ocupada
  a esa hora por otro docente, o la versión es idéntica a la vigente.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Asignatura,
    Aula,
    BloqueHorario,
    Docente,
    Grupo,
    Horario,
    Periodo,
    Usuario,
)
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, instantanea

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]
CAMPOS = ["docente_id", "periodo_id", "version", "estado", "origen", "notas"]


@dataclass(frozen=True)
class BloqueEntrada:
    dia: int  # 0 = lunes … 5 = sábado
    hora_inicio: time
    hora_fin: time
    asignatura_id: int
    grupo_id: int | None = None
    aula_id: int | None = None


def _texto_bloque(dia: int, inicio: time, fin: time) -> str:
    return f"{DIAS[dia]} {inicio:%H:%M}–{fin:%H:%M}"


def _se_traslapan(a_inicio: time, a_fin: time, b_inicio: time, b_fin: time) -> bool:
    return a_inicio < b_fin and b_inicio < a_fin


# --- Consulta -----------------------------------------------------------------


def obtener(sesion: Session, id_: int) -> Horario:
    horario = sesion.get(Horario, id_)
    if horario is None:
        raise NoEncontrado("El horario")
    return horario


def listar(
    sesion: Session,
    docente_id: int | None = None,
    periodo_id: int | None = None,
    estado: str | None = None,
) -> list[Horario]:
    consulta = select(Horario).order_by(Horario.periodo_id.desc(), Horario.version.desc())
    if docente_id is not None:
        consulta = consulta.where(Horario.docente_id == docente_id)
    if periodo_id is not None:
        consulta = consulta.where(Horario.periodo_id == periodo_id)
    if estado is not None:
        consulta = consulta.where(Horario.estado == estado)
    return list(sesion.scalars(consulta))


def vigente(sesion: Session, docente_id: int, periodo_id: int) -> Horario | None:
    return sesion.scalar(
        select(Horario).where(
            Horario.docente_id == docente_id,
            Horario.periodo_id == periodo_id,
            Horario.estado == "vigente",
        )
    )


# --- Validaciones ---------------------------------------------------------------


def validar_bloques(sesion: Session, bloques: list[BloqueEntrada]) -> list[str]:
    """Devuelve la lista de errores (vacía si todo está bien)."""
    errores: list[str] = []
    for b in bloques:
        if not 0 <= b.dia <= 5:
            errores.append(f"Día inválido: {b.dia}")
            continue
        if b.hora_fin <= b.hora_inicio:
            errores.append(
                f"{_texto_bloque(b.dia, b.hora_inicio, b.hora_fin)}: la hora de fin "
                "debe ser posterior a la de inicio"
            )
        asignatura = sesion.get(Asignatura, b.asignatura_id)
        if asignatura is None or not asignatura.activo:
            errores.append(
                f"{_texto_bloque(b.dia, b.hora_inicio, b.hora_fin)}: la asignatura "
                "no existe o está inactiva"
            )
        elif asignatura.tipo == "materia" and b.grupo_id is None:
            errores.append(
                f"{_texto_bloque(b.dia, b.hora_inicio, b.hora_fin)}: la materia "
                f"{asignatura.nombre} necesita grupo"
            )
        for modelo, id_, nombre in ((Grupo, b.grupo_id, "el grupo"), (Aula, b.aula_id, "el aula")):
            if id_ is not None:
                obj = sesion.get(modelo, id_)
                if obj is None or not obj.activo:
                    errores.append(
                        f"{_texto_bloque(b.dia, b.hora_inicio, b.hora_fin)}: "
                        f"{nombre} no existe o está inactiva"
                    )

    # Traslapes y duplicados dentro del mismo horario.
    ordenados = sorted(bloques, key=lambda b: (b.dia, b.hora_inicio))
    for i, a in enumerate(ordenados):
        for b in ordenados[i + 1 :]:
            if b.dia != a.dia or b.hora_inicio >= a.hora_fin:
                break
            if _se_traslapan(a.hora_inicio, a.hora_fin, b.hora_inicio, b.hora_fin):
                tipo = "repetido" if a == b else "se traslapa con"
                errores.append(
                    f"{_texto_bloque(a.dia, a.hora_inicio, a.hora_fin)} {tipo} "
                    f"{_texto_bloque(b.dia, b.hora_inicio, b.hora_fin)}"
                )
    return errores


def advertencias(sesion: Session, horario: Horario) -> list[str]:
    """Situaciones que no impiden confirmar pero que el administrador debe revisar."""
    avisos: list[str] = []
    if not horario.bloques:
        return avisos

    # El aula ya está ocupada a esa hora por otro docente (horarios vigentes del periodo).
    otros = sesion.scalars(
        select(BloqueHorario)
        .join(Horario)
        .where(
            Horario.periodo_id == horario.periodo_id,
            Horario.estado == "vigente",
            Horario.docente_id != horario.docente_id,
            BloqueHorario.aula_id.is_not(None),
        )
    ).all()
    for b in horario.bloques:
        if b.aula_id is None:
            continue
        for o in otros:
            if (
                o.aula_id == b.aula_id
                and o.dia == b.dia
                and _se_traslapan(b.hora_inicio, b.hora_fin, o.hora_inicio, o.hora_fin)
            ):
                cuando = _texto_bloque(b.dia, b.hora_inicio, b.hora_fin)
                avisos.append(
                    f"Aula {b.aula.clave} ocupada el {cuando}: {o.horario.docente.nombre} la "
                    f"tiene de {o.hora_inicio:%H:%M} a {o.hora_fin:%H:%M} ({o.asignatura.nombre})"
                )

    # Versión idéntica a la vigente: probablemente un duplicado.
    actual = vigente(sesion, horario.docente_id, horario.periodo_id)
    if actual is not None and actual.id != horario.id and _firma(actual) == _firma(horario):
        avisos.append(f"Esta versión es idéntica a la vigente (versión {actual.version})")
    return avisos


def _firma(horario: Horario) -> list[tuple]:
    return sorted(
        (b.dia, b.hora_inicio, b.hora_fin, b.asignatura_id, b.grupo_id, b.aula_id)
        for b in horario.bloques
    )


def _bloques_dict(horario: Horario) -> list[dict]:
    return [
        {
            "dia": DIAS[b.dia],
            "inicio": b.hora_inicio,
            "fin": b.hora_fin,
            "asignatura_id": b.asignatura_id,
            "grupo_id": b.grupo_id,
            "aula_id": b.aula_id,
        }
        for b in horario.bloques
    ]


# --- Operaciones ----------------------------------------------------------------


def _exigir_periodo_abierto(periodo: Periodo) -> None:
    if periodo.estado == "cerrado":
        raise ErrorNegocio(
            f"El periodo {periodo.nombre} está cerrado: sus horarios son de solo lectura", 409
        )


def _exigir_borrador(horario: Horario) -> None:
    if horario.estado != "borrador":
        raise ErrorNegocio(
            f"Solo se modifican borradores; esta versión está {horario.estado}. "
            "Crea una nueva versión para hacer cambios.",
            409,
        )


def crear_borrador(
    sesion: Session,
    usuario: Usuario,
    docente_id: int,
    periodo_id: int,
    basado_en_id: int | None = None,
    origen: str = "manual",
    notas: str = "",
) -> Horario:
    """Crea una nueva versión en borrador, vacía o copiando los bloques de otra versión."""
    docente = sesion.get(Docente, docente_id)
    if docente is None:
        raise NoEncontrado("El docente")
    if not docente.activo:
        raise ErrorNegocio(f"El docente {docente.nombre} está inactivo", 409)
    periodo = sesion.get(Periodo, periodo_id)
    if periodo is None:
        raise NoEncontrado("El periodo")
    _exigir_periodo_abierto(periodo)

    base = None
    if basado_en_id is not None:
        base = obtener(sesion, basado_en_id)
        if (base.docente_id, base.periodo_id) != (docente_id, periodo_id):
            raise ErrorNegocio("La versión base debe ser del mismo docente y periodo")

    ultima = sesion.scalar(
        select(func.max(Horario.version)).where(
            Horario.docente_id == docente_id, Horario.periodo_id == periodo_id
        )
    )
    horario = Horario(
        docente_id=docente_id,
        periodo_id=periodo_id,
        version=(ultima or 0) + 1,
        estado="borrador",
        origen=origen,
        notas=notas,
        basado_en_id=base.id if base else None,
        creado_por_id=usuario.id,
    )
    if base is not None:
        horario.bloques = [
            BloqueHorario(
                dia=b.dia,
                hora_inicio=b.hora_inicio,
                hora_fin=b.hora_fin,
                asignatura_id=b.asignatura_id,
                grupo_id=b.grupo_id,
                aula_id=b.aula_id,
            )
            for b in base.bloques
        ]
    sesion.add(horario)
    sesion.flush()
    auditar(
        sesion,
        usuario,
        "crear",
        "horario",
        horario.id,
        despues={**instantanea(horario, CAMPOS), "basado_en_id": horario.basado_en_id},
    )
    sesion.commit()
    return horario


def editar_datos(sesion: Session, usuario: Usuario, id_: int, notas: str) -> Horario:
    horario = obtener(sesion, id_)
    _exigir_periodo_abierto(horario.periodo)
    _exigir_borrador(horario)
    antes = instantanea(horario, CAMPOS)
    horario.notas = notas
    auditar(sesion, usuario, "editar", "horario", horario.id, antes, instantanea(horario, CAMPOS))
    sesion.commit()
    return horario


def reemplazar_bloques(
    sesion: Session, usuario: Usuario, id_: int, bloques: list[BloqueEntrada]
) -> Horario:
    horario = obtener(sesion, id_)
    _exigir_periodo_abierto(horario.periodo)
    _exigir_borrador(horario)
    errores = validar_bloques(sesion, bloques)
    if errores:
        raise ErrorNegocio("El horario tiene errores", 422, errores)
    antes = _bloques_dict(horario)
    horario.bloques = [BloqueHorario(**b.__dict__) for b in bloques]
    sesion.flush()
    sesion.refresh(horario)
    auditar(
        sesion,
        usuario,
        "editar_bloques",
        "horario",
        horario.id,
        antes={"bloques": antes},
        despues={"bloques": _bloques_dict(horario)},
    )
    sesion.commit()
    return horario


def confirmar(sesion: Session, usuario: Usuario, id_: int, aceptar_advertencias: bool) -> Horario:
    """Convierte un borrador en la versión vigente. La anterior pasa a histórico."""
    horario = obtener(sesion, id_)
    _exigir_periodo_abierto(horario.periodo)
    _exigir_borrador(horario)
    if not horario.bloques:
        raise ErrorNegocio("No se puede confirmar un horario sin actividades", 422)
    avisos = advertencias(sesion, horario)
    if avisos and not aceptar_advertencias:
        raise ErrorNegocio("Revisa las advertencias antes de confirmar", 409, avisos)

    anterior = vigente(sesion, horario.docente_id, horario.periodo_id)
    if anterior is not None:
        anterior.estado = "historico"
        auditar(
            sesion,
            usuario,
            "reemplazar",
            "horario",
            anterior.id,
            antes={"estado": "vigente"},
            despues={"estado": "historico", "reemplazado_por": horario.id},
        )
        sesion.flush()  # libera el índice de "un vigente" antes de marcar el nuevo
    horario.estado = "vigente"
    horario.confirmado_por_id = usuario.id
    horario.confirmado_en = datetime.now(UTC)
    auditar(
        sesion,
        usuario,
        "confirmar",
        "horario",
        horario.id,
        antes={"estado": "borrador"},
        despues={"estado": "vigente", "advertencias_aceptadas": avisos},
    )
    sesion.commit()
    return horario


def descartar(sesion: Session, usuario: Usuario, id_: int) -> Horario:
    horario = obtener(sesion, id_)
    _exigir_borrador(horario)
    horario.estado = "descartado"
    auditar(
        sesion,
        usuario,
        "descartar",
        "horario",
        horario.id,
        antes={"estado": "borrador"},
        despues={"estado": "descartado"},
    )
    sesion.commit()
    return horario
