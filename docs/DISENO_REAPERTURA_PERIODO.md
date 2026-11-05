# Diseño: reabrir excepcionalmente un periodo cerrado

Estado: **propuesta para revisión**. No hay código ni cambios en la base de datos.

## 1. Para qué sirve

Al cambiar de semestre, el periodo anterior se **cierra**: sus horarios, asistencias e
importaciones quedan de solo lectura y se conservan como historial. Excepcionalmente
puede hacer falta corregir algo de un periodo cerrado, por ejemplo:

- Un justificante que llegó tarde y hay que registrar en una falta de noviembre.
- Una asistencia mal capturada que se descubre al revisar los reportes del semestre.

Reabrir debe ser **raro, explícito, temporal y auditado**, y **nunca** debe cambiar por sí
solo las asistencias ya registradas.

## 2. Lo que hoy impone el sistema (sin cambiar la base de datos)

| Regla actual | Efecto en el diseño |
|---|---|
| Estados posibles: `borrador`, `activo`, `cerrado` (restricción de la base) | No existe un estado «reabierto»; crearlo exige una migración |
| Solo **un** periodo puede estar `activo` (índice único en la base) | Un periodo cerrado no puede estar abierto al mismo tiempo que el semestre en curso |
| Un periodo `borrador` no se toma en cuenta para la bitácora | Reabrir como borrador ocultaría el historial: **descartado** |
| Cerrado bloquea registrar y corregir asistencia, crear horarios e importar | Consultas y reportes siempre funcionan |
| Cada asistencia guarda una copia del docente, horario, bloque, materia y minutos | Reabrir no recalcula nada: las asistencias registradas no cambian |
| Toda acción sobre periodos se guarda en la auditoría (antes, después, usuario y fecha) | La reapertura y el nuevo cierre quedan registrados sin cambios en la base |

## 3. Propuesta

### Fase 1 — sin cambios en la base de datos (se puede hacer ya, si se autoriza)

**«Abrir un periodo anterior para corrección»**, en Administración › Periodos, solo para
quien tiene el permiso `periodos.gestionar` (el administrador).

Por la regla de «un solo periodo activo», la reapertura es un **intercambio guiado**:

1. El administrador elige el periodo cerrado y escribe el **motivo** (obligatorio, mínimo
   15 caracteres; por ejemplo «Registrar justificante oficio 123 del 12/11/2026»).
2. La aplicación muestra un aviso claro:
   - Mientras dure la corrección, **el semestre actual queda en pausa**: no se podrá
     registrar asistencia de hoy ni importar horarios del semestre actual.
   - Las asistencias ya registradas **no cambian**; solo se podrán corregir una por una,
     cada corrección con su propio motivo (como hoy).
   - Se recomienda hacerlo fuera del horario de captura.
3. Confirmación reforzada: escribir el nombre del periodo (p. ej. `AGOSTO - DICIEMBRE 2026`).
4. El servidor, en **una sola operación** (todo o nada):
   - pone el periodo actual de `activo` a `cerrado`;
   - pone el periodo anterior de `cerrado` a `activo`;
   - guarda en la auditoría la acción `reabrir`, con el motivo, el periodo pausado y el usuario.
5. En la barra superior aparece un aviso permanente en color de advertencia:
   «**Corrigiendo AGOSTO - DICIEMBRE 2026** — semestre actual en pausa ·
   [Terminar corrección]».
6. **Terminar corrección** hace el intercambio inverso en una sola operación y lo audita como
   `terminar_reapertura`. El aviso desaparece.

Por qué se puede hacer sin migraciones: solo usa los tres estados existentes, respeta el
índice de «un solo activo» y la auditoría ya guarda antes, después y motivo en formato
libre. El servicio sabe que hay una reapertura en curso consultando la última acción
`reabrir` sin su `terminar_reapertura` correspondiente.

**Protecciones:**

- No se puede reabrir si ya hay otra reapertura en curso.
- No se puede reabrir un periodo que nunca estuvo activo.
- No se recalculan asistencias, minutos ni reportes. Los reportes del periodo reabierto
  reflejan solo las correcciones que el administrador haga a mano.
- Crear o confirmar horarios en un periodo reabierto pide además una **fecha de vigencia
  explícita**, para que las fechas ya registradas sigan usando la versión que tenían.
- Si la aplicación se cierra sin terminar, el aviso reaparece al entrar (el estado vive en
  el servidor, no en la computadora).

**Limitación de la fase 1:** mientras dura la corrección, el semestre en curso no admite
capturas. Para correcciones cortas (minutos) es aceptable; para correcciones largas no.

### Fase 2 — con cambio en la base de datos (solo con autorización posterior)

Agregar un estado `reabierto` (o una marca «reabierto hasta») que **conviva** con el
periodo activo, con fecha límite y cierre automático al vencer. Así el semestre en curso
sigue funcionando mientras se corrige el anterior. Requiere:

- una migración compatible (ampliar la restricción de estados; no borra ni modifica datos);
- probarla solo en la base de pruebas, como se hizo con las demás.

## 4. Lo que verá el usuario

- **Administración › Periodos:** en un periodo cerrado, el botón «Abrir para corrección…».
- **Barra superior:** el aviso de corrección en curso, con su botón para terminar.
- **Registro de cambios:** las reaperturas aparecen con su motivo, usuario y fecha.
- **Rol de consulta:** no ve los botones; sí ve el aviso, para saber que hay una
  corrección en curso.

## 5. Pruebas previstas

- Reabrir pide motivo y confirmación; queda auditado con usuario, motivo y periodo pausado.
- Intercambio atómico: si falla una parte, no cambia nada.
- Las asistencias registradas antes de reabrir conservan sus valores después de reabrir y
  después de terminar.
- No se puede reabrir dos veces a la vez, ni desde el rol de consulta (403).
- Terminar restaura exactamente el periodo que estaba activo.
- La interfaz muestra y oculta el aviso de la barra superior.

## 6. Decisión que necesitamos

1. ¿Se autoriza la **fase 1** (sin migraciones), aceptando que el semestre actual queda en
   pausa durante la corrección?
2. ¿O se prefiere esperar a la **fase 2**, que necesita una migración autorizada?
