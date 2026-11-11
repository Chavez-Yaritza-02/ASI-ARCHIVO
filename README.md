# ASI-ARCHIVO

Sistema de Asistencia y Archivo Digital — Jefatura de Electromecánica,
Tecnológico Superior de Jalisco, campus Zapopan.

La arquitectura, el modelo de datos y las etapas están en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (administra Python 3.12 y las dependencias)
- PostgreSQL 17

## Configuración en macOS (desarrollo)

```bash
# 1. Herramientas
brew install uv postgresql@17
brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

# 2. Bases de datos locales (desarrollo y pruebas)
createuser asi_dev
psql postgres -c "ALTER USER asi_dev WITH PASSWORD 'elige-una-contrasena';"
createdb -O asi_dev asi_archivo
createdb -O asi_dev asi_archivo_test

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
> oficiales. Las apps de producción para Windows se generarán en la Etapa 8.

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

Después de actualizar el código, aplica las migraciones nuevas antes de abrir la app:

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
   al historial.

El rol **consulta** puede ver todo, pero no ve los botones de edición; la API también
rechaza cualquier cambio que intente.

## Pruebas y estilo

```bash
uv run pytest            # usa la base de datos asi_archivo_test
uv run ruff check .      # reglas de estilo
uv run ruff format .     # formato automático
```

GitHub Actions ejecuta lo mismo en cada *push* ([.github/workflows/pruebas.yml](.github/workflows/pruebas.yml)).

## Prueba de OCR (Etapa 1b)

La herramienta de [herramientas/ocr_prueba/](herramientas/ocr_prueba/) extrae horarios de
PDFs escaneados y mide su precisión. Resultados y método en
[docs/EVALUACION_OCR.md](docs/EVALUACION_OCR.md). Requiere Tesseract
(`brew install tesseract tesseract-lang`) y el grupo de dependencias `ocr`:

```bash
uv run --group ocr python herramientas/ocr_prueba/extraer.py CARPETA_PDFS salida.json
```

## Datos institucionales

No subas al repositorio archivos reales (horarios, oficios, `.env`). El archivo
`.gitignore` ya excluye `.env`, `datos/` y archivos `.zip`.
