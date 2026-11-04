# ASI-ARCHIVO — Arquitectura

Sistema de Asistencia y Archivo Digital de la Jefatura de Electromecánica,
Tecnológico Superior de Jalisco, campus Zapopan.

> Documento vivo: se actualiza al cerrar cada etapa. Última actualización: Etapa 1.

## 1. Objetivo

Centralizar los horarios docentes, la bitácora diaria de asistencia y el archivo
de documentos de la Jefatura. Debe poder consultarse desde dos computadoras Windows
de la universidad y desde una MacBook, con la misma información en las tres.

## 2. Principios de diseño

1. **Nunca suponer asistencia.** Un docente sin registro del día está *pendiente*.
   El estado "pendiente" no se guarda: es la ausencia de un registro.
2. **El historial no se rompe.** Los horarios se versionan con fechas de vigencia
   en lugar de sobrescribirse. Una falta de septiembre sigue mostrando el horario
   que estaba vigente en septiembre.
3. **No se borra nada.** Los registros se desactivan (*soft delete*) y cada cambio
   queda en la tabla `auditoria`. La base de datos impide modificar o borrar la auditoría.
4. **Ubicación programada ≠ presencia confirmada.** El buscador muestra dónde
   *debería* estar un docente según su horario. Eso es distinto de que su presencia
   esté registrada.
5. **Sin secretos en el código.** Las credenciales viven en `.env` (fuera de Git)
   o en el llavero del sistema operativo.
6. **Los datos reales no salen sin autorización.** El OCR corre en el servidor propio
   (Tesseract), no en servicios en la nube.

## 3. Arquitectura general

```
 [PC Windows asistente] ─┐
 [PC Windows jefe]   ────┼── HTTPS + token ──► [API FastAPI] ──► [PostgreSQL]
 [MacBook]           ────┘                          │
     (PySide6)                                      ├──► [Almacén de archivos]
                                                    └──► [OCR / Reportes]
```

- **Cliente (PySide6):** solo muestra la información y la envía a la API. No contiene
  reglas de negocio ni credenciales de la base de datos.
- **API (FastAPI):** concentra la lógica, valida los datos, verifica permisos y
  escribe la auditoría.
- **PostgreSQL:** la única fuente de verdad.
- **OCR y reportes:** se procesan en el servidor, así que el resultado es igual en
  Windows y en Mac, y Tesseract no se instala en cada PC.

### Tecnologías

| Área | Tecnología | Motivo |
|---|---|---|
| Lenguaje | Python 3.12 | Un solo lenguaje en cliente y servidor |
| Interfaz | PySide6 (Qt 6) | Escritorio nativo en Windows y macOS; licencia LGPL |
| API | FastAPI + Pydantic | Validación automática y documentación en `/docs` |
| Base de datos | PostgreSQL 17 | Robusta, con búsqueda de texto en español, JSONB, `pg_trgm` y `unaccent` |
| ORM / migraciones | SQLAlchemy 2 + Alembic | Cambios de esquema controlados y reversibles |
| Contraseñas | Argon2 (`argon2-cffi`) | Algoritmo recomendado actualmente para guardar contraseñas |
| Sesión | JWT firmado (`pyjwt`) | Sin estado en el servidor; expira en 8 h |
| Token en el cliente | `keyring` | Llavero de Windows / Llavero de macOS |
| Dependencias | `uv` (espacio de trabajo) | Instalación rápida y reproducible (`uv.lock`) |
| Calidad | `ruff` + `pytest` + GitHub Actions | Estilo uniforme y pruebas en cada *push* |
| OCR (Etapa 3) | PyMuPDF + Tesseract | Primero se lee el texto digital del PDF; el OCR solo se usa si no hay texto |
| Reportes (Etapa 7) | Jinja2 + WeasyPrint, `openpyxl` | PDF desde plantillas HTML y Excel nativo |
| Ejecutables (Etapa 8) | PyInstaller | `.exe` para Windows y `.app` para macOS |

## 4. Estructura del repositorio

```
ASI-ARCHIVO/
├── pyproject.toml          # espacio de trabajo uv, ruff y pytest
├── uv.lock                 # versiones exactas de dependencias
├── .env.example            # plantilla de configuración (sin secretos)
├── shared/asi_shared/      # constantes comunes: estados de asistencia, permisos
├── server/
│   ├── alembic.ini
│   ├── migrations/         # migraciones de la base de datos
│   ├── app/
│   │   ├── main.py         # punto de entrada de la API
│   │   ├── cli.py          # comandos de administración (crear usuarios)
│   │   ├── api/            # endpoints por módulo + dependencias de permisos
│   │   ├── core/           # configuración y seguridad
│   │   ├── db/             # conexión a PostgreSQL
│   │   └── models/         # tablas (SQLAlchemy)
│   └── tests/
├── client/
│   ├── asi_cliente/
│   │   ├── main.py         # arranque de la app de escritorio
│   │   ├── api/            # cliente HTTP hacia la API
│   │   ├── views/          # ventanas y pantallas
│   │   └── theme/          # temas claro y oscuro
│   └── tests/
├── docs/                   # esta documentación
└── .github/workflows/      # pruebas automáticas
```

Se agregarán carpetas solo cuando se necesiten: `server/app/services/` y
`server/app/importers/` (Etapa 3), `server/app/reports/` (Etapa 7) y `deploy/` (Etapa 8).

## 5. Modelo de datos

### Implementado en la Etapa 1

| Tabla | Propósito |
|---|---|
| `usuario` | Cuentas del sistema (correo, nombre, hash de contraseña, activo) |
| `rol` | `administrador`, `consulta` |
| `permiso` | Permisos individuales, p. ej. `docentes.editar` |
| `rol_permiso`, `usuario_rol` | Relaciones muchos a muchos |
| `auditoria` | Quién hizo qué, cuándo y desde qué IP; valores antes/después en JSONB. **Solo inserción** (lo garantiza un *trigger*) |

**Roles iniciales:** `administrador` tiene los 12 permisos. `consulta` solo tiene los
permisos de lectura (`*.ver`). Los permisos se reasignan en la base de datos sin tocar código.

### Planeado

**Catálogos (Etapa 2)**
- `docente`: nombre, apellidos, nombre_normalizado (sin acentos, para búsqueda), activo.
- `asignatura`, `grupo`, `aula`, `tipo_actividad`.

**Periodos y horarios (Etapa 2)**
- `periodo`: nombre, fechas, estado `borrador | activo | cerrado`. Un índice único
  parcial garantiza que solo haya un periodo activo.
- `horario`: docente, periodo, versión, origen (`manual | pdf | excel | csv`),
  documento de origen, `vigente_desde` y `vigente_hasta`.
- `bloque_horario`: día de la semana, hora de inicio y fin, asignatura, grupo, aula y
  tipo de actividad. Los horarios **por grupo** se obtienen de esta misma tabla, así
  que no hay datos duplicados ni inconsistencias.

**Importación (Etapa 3)**
- `lote_importacion`: un ZIP, quién lo subió y su estado.
- `archivo_importado`: hash SHA-256 (para detectar duplicados), páginas y método
  (texto u OCR).
- `fila_extraida`: zona temporal para la vista previa editable; nada pasa a `horario`
  hasta que el usuario lo confirma.
- La importación usa una interfaz común de "lector" (PDF, Excel, CSV) para que agregar
  Excel o CSV después no cambie el resto del proceso.

**Asistencia (Etapa 4)**
- `asistencia_diaria`: docente, fecha, estado, motivo, observaciones, justificante y
  quién lo registró. Restricción `UNIQUE(docente, fecha)`.
- `asistencia_clase` (futuro): por bloque y fecha. Convive con la tabla diaria, así
  que los registros anteriores no se pierden.
- `incidencia`.

**Documentos (Etapa 6)**
- `categoria_documento`.
- `documento`: título, categoría, fecha, palabras clave y `tsvector` para búsqueda en
  español.
- `documento_version`: ruta en el almacén, SHA-256, tamaño, tipo MIME y quién lo subió.
- `documento_docente`: relación muchos a muchos.

## 6. Seguridad

- **Toda comunicación pasa por la API.** El cliente rechaza URLs `http://` que no
  sean de la propia computadora: en producción solo se acepta HTTPS.
- Contraseñas con Argon2. El sistema exige al menos 10 caracteres.
- El inicio de sesión fallido devuelve el mismo mensaje para un correo inexistente y
  para una contraseña incorrecta, para no revelar qué cuentas existen. Cada intento,
  correcto o fallido, se audita.
- Los tokens expiran en 8 horas. Un usuario desactivado pierde el acceso de inmediato,
  aunque tenga un token vigente.
- Los permisos se verifican en el servidor con `requiere_permiso(...)`. El cliente
  solo oculta las secciones no permitidas; eso es una comodidad, no la protección real.
- **Pendiente para la Etapa 8:**
  - Tokens de renovación revocables.
  - Límite de intentos de inicio de sesión.
  - Respaldos cifrados automáticos.
  - Revisión de seguridad.

## 7. Conexión entre equipos y alojamiento

- **Desarrollo (actual):** PostgreSQL y la API corren en la Mac (`localhost`).
- **Producción (por decidir, requiere autorización institucional):** un servidor con
  Docker Compose (PostgreSQL + API + Caddy para HTTPS automático). El acceso remoto
  sería preferentemente por una VPN tipo Tailscale, para no exponer el servicio
  públicamente.
- **Respaldos:** `pg_dump` diario más una copia del almacén de archivos, cifrados y
  guardados fuera del servidor.
- **Antes de cargar datos reales:** autorización por escrito de la Jefatura y revisión
  con TI y la Unidad de Transparencia (legislación de datos personales para sujetos
  obligados, general y de Jalisco). Mientras tanto se desarrolla con datos ficticios.

## 8. Producto mínimo viable

1. Inicio de sesión con roles. ✅ (Etapa 1)
2. Docentes y periodos.
3. Horarios: captura manual e importación asistida del ZIP de PDFs.
4. Bitácora diaria con registro de estado, motivo, justificante e historial.
5. Buscador con "¿dónde debería estar ahora?".
6. Servidor desplegado con HTTPS y respaldos.

## 9. Etapas

| Etapa | Contenido | Estado |
|---|---|---|
| 1 | Estructura, entorno, base de datos, autenticación, ventana de login, CI | ✅ Completa |
| 1b | Prueba de OCR con los PDFs reales (solo local) | Siguiente |
| 2 | Docentes, periodos, captura y edición de horarios con versiones | |
| 3 | Importación ZIP → PDF → texto/OCR → vista previa editable | |
| 4 | Bitácora diaria y registro de asistencia | |
| 5 | Buscador, horarios por grupo, cruces, ubicación programada | |
| 6 | Archivo digital de documentos | |
| 7 | Reportes PDF y Excel | |
| 8 | Servidor, instaladores, respaldos y revisión de seguridad | |

## 10. Decisiones registradas

| Fecha | Decisión | Razón |
|---|---|---|
| 2026-11-04 | Aplicación de escritorio PySide6 (no web) | Solo 3 equipos; todo en Python. La API permite agregar una versión web después |
| 2026-11-04 | PostgreSQL local vía Homebrew en desarrollo | Más ligero que Docker Desktop; Docker se reserva para el servidor |
| 2026-11-04 | SQLAlchemy síncrono | Más simple de entender y suficiente para el volumen de la Jefatura |
| 2026-11-04 | Las pruebas recrean la BD con las migraciones reales | Así también se prueba que las migraciones funcionan |
| 2026-11-04 | Importación con interfaz común de lectores | Se pidió dejar preparada la importación desde Excel y CSV |
