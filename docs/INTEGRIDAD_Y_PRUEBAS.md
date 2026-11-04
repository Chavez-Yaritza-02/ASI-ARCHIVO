# Integridad temporal y aislamiento de pruebas

## Base exclusiva

Las pruebas aceptan únicamente PostgreSQL mediante psycopg, base y usuario
`asi_archivo_pytest`, en loopback, puerto 5432. No se admiten parámetros de URL,
servicios libpq ni opciones que cambien el destino. El rol debe carecer de superusuario,
creación de bases/roles, replicación, bypass RLS y membresías de otros roles.
La validación se repite contra `current_database()` y `current_user()` en el servidor.

`conftest.py` activa el modo `pruebas` antes de recolectar módulos. La barrera global
de SQLAlchemy bloquea las conexiones antes de llamar al controlador, incluso para
engines creados directamente. La API, Alembic (incluidas conexiones inyectadas), las
fixtures y los comandos de inicialización verifican también su conexión. Los procesos
hijos heredan `ASI_ENTORNO=pruebas`; no se debe eliminar esta variable al invocarlos.
Estas barreras cubren las rutas de acceso de este repositorio; no son un aislamiento
para código malicioso que desactive las protecciones o use un controlador externo.

Preparación manual, una sola vez, con un administrador local de PostgreSQL:

```sql
CREATE ROLE asi_archivo_pytest LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS;
```

Asigna una contraseña aleatoria mediante `\password asi_archivo_pytest` en psql,
y crea **una base nueva**, sin reutilizar bases con datos:

```sql
CREATE DATABASE asi_archivo_pytest OWNER asi_archivo_pytest;
```

Configura solo `ASI_TEST_DATABASE_URL` en `.env` según `.env.example`. No cambies
`ASI_DATABASE_URL` de desarrollo. No se admite `asi_dev` para pruebas.
Si el nombre ya existe, verifica que sea exclusivamente de pruebas antes de usarlo;
no elimines ni reemplaces bases para preparar el entorno.

```bash
uv run pytest -q --tb=short
uv run ruff check .
uv run ruff format --check .
```

Las fixtures recrean el esquema únicamente dentro de la base exclusiva validada.
La base principal y la aislada de OCR no se utilizan. Todos los datos automatizados
son ficticios. CI crea el mismo rol restringido y una base nueva en un PostgreSQL
17 efímero. La contraseña del rol CI se genera aleatoriamente en cada ejecución y se enmascara;
no se guardan contraseñas en el workflow. La autenticación de aprovisionamiento sin
contraseña se limita al servicio efímero y al loopback del runner.

## Vigencias desconocidas

No se modifica la migración publicada `8b4cb2f4fef8`: podría estar aplicada en bases
existentes. Se añade `e5a001`, compatible con una instalación nueva y con la Etapa 4.
No se aplica automáticamente a las bases de desarrollo o con datos reales.

La Etapa 4 no guardaba si una fecha fue elegida o inferida. Por tanto, la migración
correctiva no certifica ninguna fecha heredada: copia los valores previos a una nueva
entrada de auditoría y pone ambas fechas en NULL, con `vigencia_confirmada=false`.
Conserva horarios, estados, versiones, bloques, asistencias y auditoría anterior.
Incluso una fecha heredada aparentemente razonable necesita revisión humana.
El estado `vigente` sigue identificando la versión oficial seleccionada, pero no
certifica su intervalo temporal. Los horarios siguen disponibles para revisión y copia.

Solo se usan fechas con `vigencia_confirmada=true` en consultas por fecha. Un horario
confirmado sin fecha explícita queda con vigencia desconocida. Una confirmación con
fecha explícita no toma automáticamente el inicio del periodo. Las restricciones
PostgreSQL impiden finales anteriores al inicio y confirmaciones sin fecha inicial.

`POST /horarios/{id}/vigencia` requiere `horarios.confirmar`, fecha inicial real,
fecha final para versiones históricas y motivo/evidencia. Valida el periodo y rechaza
traslapes con otras versiones confirmadas del mismo docente. Registra usuario, valores
anteriores, posteriores y motivo en auditoría. También permite corregir fechas ya
confirmadas. Las asistencias registradas conservan su copia de lo programado.

Ejemplo ficticio:

```json
{"desde": "2026-08-17", "hasta": "2026-10-30", "motivo": "Fechas verificadas en acta ficticia"}
```

El downgrade de `e5a001` se bloquea expresamente: no es seguro restaurar fechas
inferidas ni perder la distinción entre desconocido y confirmado. No se reescribe Git.
La prueba de actualización usa un esquema transaccional en la base exclusiva y simula
una Etapa 4 ya aplicada con fechas invertidas; comprueba preservación y auditoría.

## Validación de esta entrega

- macOS: 173 pruebas aprobadas (126 anteriores conservadas y 47 nuevas).
- Antes de desarrollar las consultas: 142 aprobadas (126 + 16 de integridad).
- Cliente sin base de datos: 13 aprobadas; CI lo ejecuta también en macOS y Windows.
- Ruff y formato: aprobados en los 100 archivos Python.
- Se verifica concordancia de modelos SQLAlchemy con el esquema migrado y actualización
  desde la Etapa 4 en un esquema transaccional de la base exclusiva.
- Las pruebas Qt usan las pantallas reales contra FastAPI y PostgreSQL con datos ficticios;
  las pruebas portables del cliente usan un transporte HTTP simulado, sin base de datos.
- Exportaciones comprobadas como PDF legible y libro Excel, incluidos cargos de firma,
  permisos y escritura literal de textos que empiezan con `=`.
- Se rechazan destinos no autorizados, roles privilegiados, parámetros de URL, redirecciones
  libpq y cambios de destino mediante `connect_args`. Las pruebas negativas de inicialización
  usan destinos ficticios; los nombres reales se verifican con controladores simulados.
- No se cambian dependencias ni se añaden documentos institucionales. `.env` sigue ignorado;
  su URL de pruebas local se cambió al nuevo rol/base exclusivos. La principal no se cambió.

Quedan para operación autorizada: aplicar la migración en cada base con datos después de
revisar su impacto y confirmar las fechas reales con evidencia. No se aplica en esta entrega
ninguna migración a la base principal ni a la base aislada de OCR. Los cambios de aula que
solo tienen descripción libre continúan requiriendo verificación humana. No se automatiza
la asignación de letras pendientes, ni se adelantan documentos de Etapa 6 o instaladores
de Etapa 8.
