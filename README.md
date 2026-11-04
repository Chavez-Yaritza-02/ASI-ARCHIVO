# ASI-ARCHIVO

Sistema de Asistencia y Archivo Digital — Jefatura de Electromecánica,
Tecnológico Superior de Jalisco, campus Zapopan.

La arquitectura, el modelo de datos y las etapas están en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (administra Python 3.12 y las dependencias)
- PostgreSQL 17
- **Solo en el servidor:** Tesseract OCR con idiomas inglés y español, para importar
  horarios en PDF. Las computadoras cliente (Windows o Mac) no lo necesitan.

## Configuración en macOS (desarrollo)

```bash
# 1. Herramientas
brew install uv postgresql@17 tesseract tesseract-lang
brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

# 2. Bases de datos locales (desarrollo y pruebas)
createuser asi_dev
psql postgres -c "ALTER USER asi_dev WITH PASSWORD 'elige-una-contrasena';"
createdb -O asi_dev asi_archivo
# Pruebas: base y rol exclusivos, sin privilegios administrativos.
createuser --no-superuser --no-createdb --no-createrole asi_archivo_pytest
psql postgres -c "\password asi_archivo_pytest"
createdb -O asi_archivo_pytest asi_archivo_pytest

# 3. Configuración: copia la plantilla y ajusta la URL y la clave secreta
cp .env.example .env

# 4. Dependencias (crea .venv con Python 3.12)
uv sync --python 3.12

# 5. Crear las tablas
cd server && uv run alembic upgrade head

# 6. Crear tu usuario administrador (la contraseña se pide en pantalla)
uv run python -m app.cli crear-usuario --correo tu@correo.mx --nombre "Tu Nombre" --rol administrador
cd ..
```

> En Windows los pasos son equivalentes: instala uv y PostgreSQL con sus instaladores
> oficiales. Si el servidor corre en Windows, instala también Tesseract (con los idiomas
> `eng` y `spa`) y, si no queda en el PATH, define
> `ASI_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`.
> Las apps de producción para Windows se generarán en la Etapa 8.

## Ejecutar

Usa dos terminales:

```bash
# Terminal 1 — API (documentación interactiva en http://127.0.0.1:8000/docs)
uv run uvicorn app.main:app --reload --app-dir server

# Terminal 2 — aplicación de escritorio
uv run asi-archivo
```

El cliente se conecta a `http://127.0.0.1:8000` por defecto. Para otro servidor, define
`ASI_SERVIDOR_URL`; fuera de la propia computadora solo se acepta `https://`.

Para una base existente, revisa primero [Integridad y pruebas](docs/INTEGRIDAD_Y_PRUEBAS.md).
La migración nueva `e5a001` conserva las versiones y audita sus fechas anteriores,
pero deja las vigencias heredadas como **desconocidas** hasta confirmación humana.
No aplica cambios automáticamente a bases reales. Una vez revisado el impacto y
autorizada la actualización de esa base, las migraciones se ejecutan así:

```bash
cd server && uv run alembic upgrade head && cd ..
```

## Uso: docentes, periodos y horarios (Etapa 2)

| Pantalla | Qué permite |
|---|---|
| **Periodos** | Crear periodos (p. ej. AGOSTO - DICIEMBRE 2026), activar uno y cerrarlo al terminar el semestre. Solo uno puede estar activo; los cerrados quedan de solo lectura |
| **Docentes** | Registrar, buscar (sin importar acentos), editar, activar y desactivar |
| **Catálogos** | Asignaturas (materias o actividades), grupos y aulas |
| **Horarios** | Elegir periodo y docente, ver todas las versiones, crear una versión nueva, editar la cuadrícula semanal y confirmar la versión vigente |

Flujo para capturar un horario:

1. Activa el periodo y da de alta docente, asignaturas, grupos y aulas.
2. En **Horarios**, elige al docente y pulsa **Nueva versión** (si ya hay una vigente, se copia).
3. Haz doble clic en una celda para asignar actividad, grupo, aula y duración. Usa
   **Supr** para vaciar celdas seleccionadas.
4. **Guardar cambios**: el servidor valida traslapes, materias sin grupo y catálogos inactivos.
5. **Confirmar como vigente** (solo administradores). Si el aula la ocupa otro docente, o
   la versión es idéntica a la vigente, se pide confirmación. La versión anterior pasa
   al historial. La interfaz solicita una fecha real explícita; la API permite omitirla,
   en cuyo caso la vigencia temporal queda desconocida y no participa en consultas por fecha.
6. **Confirmar / corregir fechas reales** permite al confirmador autorizado registrar
   inicio, fin y motivo/evidencia; los históricos requieren fecha final. Cada corrección
   queda auditada y no cambia los bloques.

El rol **consulta** puede ver todo, pero no ve los botones de edición; la API también
rechaza cualquier cambio que intente.

## Pruebas y estilo

```bash
uv run pytest -q --tb=short  # exclusivamente asi_archivo_pytest (rol restringido)
uv run ruff check .      # reglas de estilo
uv run ruff format --check .  # comprueba el formato
```

GitHub Actions ejecuta lo mismo en cada *push* ([.github/workflows/pruebas.yml](.github/workflows/pruebas.yml)).

## Uso: importar horarios desde PDF (Etapa 3)

1. En **Catálogos** captura (o revisa) aulas, asignaturas y grupos del periodo. Entre más
   completo esté el catálogo, más datos se asignan solos.
2. En **Importar horarios** elige el periodo y pulsa **Importar archivo…** (ZIP o PDF).
   El servidor hace el OCR en segundo plano; la pantalla muestra el avance.
3. Elige cada página y revísala. Colores de la cuadrícula:
   - **Verde:** coincide con el catálogo o ya lo confirmaste.
   - **Amarillo:** sugerencia; acéptala (botón o doble clic → *Aplicar*).
   - **Rojo:** falta elegir (doble clic: imagen del documento, texto leído y opción de
     crear un registro nuevo).
   - **Morado:** solo se conoce la letra del grupo; queda pendiente de validar.
4. **Aprobar: crear borrador** solo se habilita cuando no queda nada pendiente. El
   horario se crea en **borrador**: confírmalo después en **Horarios**.

Las páginas repetidas (mismo QR) se marcan como *Duplicada*, y un PDF ya importado no se
vuelve a procesar. El archivo original solo se lee: no se modifica ni se guarda.

## Uso: bitácora diaria (Etapa 4)

- **Bitácora del día:** elige la fecha (◀ ▶ u «Hoy»). Aparecen los docentes con
  actividades ese día según el horario que regía en esa fecha, un renglón por turno
  (matutino antes de las 14:00, vespertino desde las 14:00).
  - Doble clic o «Registrar / corregir»: estado, hora real de entrada y salida,
    observaciones y justificación. Si la entrada rebasa la tolerancia configurada (inicialmente 10 min), se sugiere «Retardo».
  - «Marcar seleccionados: asistió» registra varios pendientes a la vez.
  - Una corrección pide motivo; corregir días anteriores requiere autorización. El
    botón «Historial» muestra cada cambio, quién lo hizo y por qué.
  - «Nueva incidencia» agrega notas del día (comisión, permiso, cambio de aula…).
  - «Exportar PDF» o «Exportar Excel» genera la bitácora con espacio para firmas.
- **Calendario:** registra días inhábiles, vacaciones y suspensiones (todo el día o un
  turno). En esas fechas la bitácora no espera registros ni genera faltas. Un «día hábil
  (excepción)» permite trabajar en una fecha inhábil.
- Sin registro, un docente aparece como **Pendiente de verificar**: el sistema nunca
  marca faltas por su cuenta.

## Uso: consultas y ubicación programada (Etapa 5)

- **Buscador:** busca docentes, materias, grupos y aulas sin distinguir acentos.
  Filtra por carrera, semestre, periodo, día y turno. La fecha selecciona la versión
  de horario que regía entonces. Las actividades se muestran separadas de los catálogos;
  los resultados se paginan, hasta 100 por categoría en la interfaz.
- **Horarios por grupo:** filtra carrera, semestre, letra y periodo, busca grupos,
  selecciona uno y consulta su semana. Cada clase muestra fecha, materia, docente,
  aula y horas. Los traslapes quedan señalados. **Exportar PDF / Excel** respeta el
  permiso de generación de reportes y conserva los cargos de firma sin nombres personales.
  Una semana puede combinar versiones diferentes si hubo un cambio durante ella.
- **Ubicación programada:** busca docente y consulta una fecha y hora local de la
  Jefatura. Muestra actividades programadas, suspensiones e incidencias registradas.
  Siempre distingue programación de presencia física. Sin clase o con fechas desconocidas
  se informa expresamente. Los cambios de aula guardados como texto libre se muestran
  como avisos y dejan el aula efectiva por verificar: no se interpreta su texto como destino.
- **Tolerancia de retardos:** comienza en 10 minutos; solo el rol administrador puede
  cambiarla (0–120 minutos), con auditoría. Se aplica al volver a consultar la bitácora.

Las fechas desconocidas nunca se sustituyen por el inicio del periodo. Las versiones
siguen disponibles en **Horarios** para que un confirmador autorizado registre las
fechas verificadas. No se completan automáticamente las letras pendientes de grupos.
Los filtros de horarios requieren `horarios.ver`; las consultas que muestran calendario
o incidencias también requieren `asistencia.ver`. La ubicación necesita además
`docentes.ver`, y exportar requiere `reportes.generar`. La API aplica estas reglas aunque
un cliente intente saltarse los botones ocultos.

Los detalles de la migración correctiva, preparación de la base de pruebas y verificaciones
están en [Integridad y pruebas](docs/INTEGRIDAD_Y_PRUEBAS.md).

## Datos reales y base aislada

Los documentos reales se guardan fuera del repositorio, en `~/ASI-ARCHIVO-DATOS/`. Esa
carpeta no se sincroniza con la nube y tiene permisos solo para su dueño. Para pruebas
con datos reales existe una base de datos aparte, `asi_archivo_ocr`, con su propio usuario.
Sus credenciales están en `~/ASI-ARCHIVO-DATOS/etapa3/.env.ocr`. Para levantar la API
contra esa base:

```bash
set -a && source ~/ASI-ARCHIVO-DATOS/etapa3/.env.ocr && set +a
uv run uvicorn app.main:app --app-dir server --port 8001
```

Para eliminarla por completo: `dropdb asi_archivo_ocr && dropuser asi_ocr`.

## Prueba de OCR (Etapa 1b)

La herramienta de [herramientas/ocr_prueba/](herramientas/ocr_prueba/) aplica el mismo
OCR del importador a una carpeta de PDFs y mide su precisión contra una transcripción
verificada. Resultados y método en [docs/EVALUACION_OCR.md](docs/EVALUACION_OCR.md):

```bash
uv run python herramientas/ocr_prueba/extraer.py CARPETA_PDFS salida.json
```

## Datos institucionales

No subas al repositorio archivos reales (horarios, oficios, `.env`). El archivo
`.gitignore` ya excluye `.env`, `datos/` y archivos `.zip`.
