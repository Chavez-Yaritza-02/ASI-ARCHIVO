# Etapa 2 · Compatibilidad de la base con SQLite

Parte del [plan de la aplicación local](https://github.com/Chavez-Yaritza-02/ASI-ARCHIVO/blob/plan-aplicacion-local/docs/PLAN_APLICACION_LOCAL.md).
Rama `sqlite-compatibilidad` (desde `entrega-v1`), **sin merge**.

## Alcance

El mismo código funciona con **PostgreSQL** (servidor actual, sin cambios) y con **SQLite**
(futura aplicación local). No se migraron datos, no se tocó ninguna base real ni de
revisión, no se modificaron migraciones publicadas y no se eliminó PostgreSQL ni FastAPI.

## Qué se adaptó

| Pieza de PostgreSQL | Equivalente en SQLite | Dónde |
|---|---|---|
| Columnas `JSONB` (auditoría, encabezado del OCR) | `JSON`; en PostgreSQL sigue siendo `JSONB` | `app/db/tipos.py` |
| Fechas con zona horaria | Se guardan en UTC y se devuelven con zona | `FechaHora` |
| `now()` (microsegundos) | Hora con milisegundos, necesaria para el sello de las sesiones | `ahora_bd()` |
| Reglas con `EXTRACT(EPOCH …)` (duración de cada hora) | `strftime('%s', …)`; en PostgreSQL el texto es idéntico al anterior | `segundos_entre()` |
| Triggers que impiden modificar la auditoría y borrar el archivo digital | 6 triggers SQLite con los mismos mensajes | `app/db/sqlite_local.py` |
| Índices únicos parciales (periodo activo, horario vigente) | `sqlite_where` | modelos de horarios |
| Bloqueos `SELECT … FOR UPDATE` y bloqueo por IP del inicio de sesión | Cada petición reserva la base al empezar (`BEGIN IMMEDIATE`): un solo escritor a la vez | `sqlite_local`, `sesion.py`, `auth.py` |
| Datos iniciales de las migraciones (roles, permisos, categorías, tolerancia) | Módulo propio, comprobado contra PostgreSQL migrado | `app/db/datos_iniciales.py` |
| Versión del esquema (`alembic_version`) | Se registra la equivalente (`e6a001`) al crear la base local | `crear_esquema()` |

**Base local nueva:** `crear_esquema()` crea las tablas, las protecciones, los datos iniciales
y la versión del esquema. Se niega a actuar sobre una base que ya tenga tablas.

**Un ajuste que también beneficia al servidor:** al subir un archivo de horarios, la
petición cierra su sesión antes de que empiece el OCR.

## Resultados de las pruebas

| Base | Resultado |
|---|---|
| PostgreSQL (como hoy) | **389 aprobadas, 0 fallidas** |
| SQLite (base temporal nueva) | **382 aprobadas, 0 fallidas, 7 omitidas** |

Pruebas nuevas (`test_sqlite_compatibilidad.py`, 14):
- Base local completa: tablas, protecciones, llaves foráneas y diario WAL.
- No se recrea una base existente.
- **Datos iniciales idénticos a los de las migraciones de PostgreSQL.**
- La auditoría no se modifica ni se borra.
- El archivo digital no se borra.
- Reglas de duración en la sintaxis de cada base.
- Fechas con zona horaria.
- Versión del esquema igual a la última migración.
- Barrera que rechaza bases SQLite no autorizadas (4 casos).

Las 7 omitidas en SQLite son propias de PostgreSQL y siguen corriendo en él:
- Migraciones de Alembic (2).
- Barreras de conexión de PostgreSQL (3).
- Inmutabilidad escrita con SQL de PostgreSQL (1); su equivalente para SQLite está en las
  pruebas nuevas.
- Comparación de los datos iniciales contra la base PostgreSQL migrada (1); corre en la
  suite de PostgreSQL.

La comparación automática entre los modelos y el esquema migrado de PostgreSQL sigue
pasando: **el esquema del servidor no cambió**.

**Integración continua:** GitHub Actions corre ahora la suite en PostgreSQL y también en SQLite.

## Hallazgos durante la etapa

1. **Reservar la base en cada lectura bloqueaba todo.** La primera versión reservaba SQLite
   en exclusiva también al consultar; una consulta que quedaba abierta hacía esperar a las
   demás. Ahora solo reservan las sesiones de la aplicación, que son cortas.
2. **El sello de las sesiones dependía de la precisión de la hora.** Con hora al segundo,
   desactivar y reactivar una cuenta en el mismo segundo dejaba válido un token anterior.
   Se corrigió con milisegundos.
3. **El OCR esperaba a la petición que subió el archivo.** Se corrigió cerrando la sesión
   antes de procesar.

## Pendiente para las siguientes etapas

- **Integrar el rediseño de asistencia** (`asistencia-rediseno`). Los archivos casi no se
  superponen; se comprobará con la suite en ambas bases.
- **Etapa 3:** modo local integrado y cuenta única de administrador con recuperación.
- **Migraciones futuras** que funcionen en ambas bases (Alembic en modo `batch` para SQLite).
- **Probar en Windows** la suite con SQLite (OCR con Tesseract incluido).
