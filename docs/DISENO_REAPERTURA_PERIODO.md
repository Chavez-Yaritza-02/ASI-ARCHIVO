# Diseño técnico: reabrir excepcionalmente un periodo cerrado (fase 2)

Estado: **diseño técnico para aprobación**. La migración está como **borrador** en
[docs/fase2/f2r001_reapertura_periodo.py](fase2/f2r001_reapertura_periodo.py), fuera de la
carpeta de migraciones: no se ha ejecutado en ninguna base.

Decisión de la Jefatura: se elige la **fase 2**. Debe permitir corregir horarios de
semestres anteriores **sin suspender** el registro de asistencias del semestre actual.
(La fase 1 —intercambio de periodos con pausa del semestre— queda descartada.)

---

## 1. Objetivo y reglas

- Un administrador puede **abrir para corrección** un periodo cerrado, con **motivo**,
  **confirmación** y **plazo** (máximo 30 días).
- El periodo activo **sigue activo**: la asistencia de hoy se registra normalmente.
- Mientras la reapertura esté vigente, en el periodo reabierto se puede: crear y confirmar
  versiones de horario, importar horarios y corregir asistencias, cada acción con su
  auditoría y sus reglas de siempre.
- La reapertura **termina** al pulsar «Terminar corrección» o **automáticamente** al vencer
  el plazo. No hace falta ningún proceso programado: el sistema compara la fecha al consultar.
- **Nada se recalcula ni se modifica solo.** Las asistencias registradas guardan su propia
  copia de docente, horario, bloque, materia y minutos; reabrir no las toca.
- Todo queda en el historial: quién abrió, por qué, hasta cuándo, quién cerró y cómo.

## 2. Por qué una tabla nueva y no un estado nuevo

| Opción | Efecto | Decisión |
|---|---|---|
| Agregar el estado `reabierto` a `periodo` | Hay que cambiar la restricción de estados y revisar el índice de «un solo activo» y todas las consultas que filtran por estado | Descartada |
| **Tabla `reapertura_periodo`** | Cambio 100 % aditivo; `periodo` no cambia; cada reapertura queda como historial propio | **Elegida** |

El periodo reabierto **sigue con estado `cerrado`**. Lo que cambia es la regla de escritura:
«cerrado» deja de significar «siempre de solo lectura» y pasa a significar «de solo lectura,
salvo que tenga una reapertura vigente».

## 3. Migración propuesta (`f2r001`, después de `e6a001`)

Ver el borrador: [docs/fase2/f2r001_reapertura_periodo.py](fase2/f2r001_reapertura_periodo.py).

| Elemento | Detalle |
|---|---|
| Tabla `reapertura_periodo` | `periodo_id`, `motivo` (≥ 15 caracteres), `abierta_por_id`, `abierta_en`, `vence_en` (≤ 30 días), `cerrada_por_id`, `cerrada_en`, `motivo_cierre` |
| Índice único parcial | Una sola reapertura sin cerrar por periodo |
| Disparador `trg_reapertura_inmutable` | Prohíbe borrar; solo deja registrar el cierre, una vez |
| Permisos (`servidor/db/permisos.sql`) | Añadir `REVOKE DELETE ON reapertura_periodo FROM asi_app;` |
| Reversión (`downgrade`) | Solo para la base de pruebas; en producción no se revierte |

No borra, no renombra y no modifica datos existentes. El vencimiento automático se registra
al primer acceso posterior al plazo (`cerrada_por_id` = quien consultó, `motivo_cierre` =
«Venció el plazo»), para que el historial siempre diga cómo terminó.

## 4. Cambios en el servidor (cuando se autorice)

1. **Modelo** `ReaperturaPeriodo` en `app/models/horarios.py`.
2. **Servicio** `app/services/periodos.py`:
   - `reabrir(periodo_id, motivo, dias)`: solo periodos `cerrado`, sin reapertura vigente;
     audita `reabrir`.
   - `terminar_reapertura(periodo_id, motivo)`: audita `terminar_reapertura`.
   - `reapertura_vigente(periodo)`: devuelve la vigente y cierra las vencidas.
   - `admite_cambios(periodo)`: `activo` o (`cerrado` con reapertura vigente).
3. **Una sola regla de escritura.** Hoy hay tres comprobaciones separadas de «periodo
   cerrado» (`horarios._exigir_periodo_abierto`, `bitacora._exigir_periodo_abierto`,
   `importacion` al subir). Las tres pasan a usar `admite_cambios`, así no queda un camino
   que se salte la regla.
4. **Endpoints** (permiso `periodos.gestionar`):
   - `POST /periodos/{id}/reabrir` · `{motivo, dias}`
   - `POST /periodos/{id}/terminar-reapertura` · `{motivo}`
   - `GET /periodos/reaperturas` (lectura, permiso `horarios.ver`): historial.
   - `PeriodoSalida` agrega `reapertura: {vence_en, motivo, abierta_por} | null`.
5. **Impacto antes de confirmar un horario** en un periodo reabierto:
   `GET /horarios/{id}/impacto` (solo lectura) devuelve, para las fechas desde la vigencia:
   horas nuevas que quedarían pendientes y asistencias ya registradas cuyo bloque deja de
   estar programado (pasarían a «Capturas fuera del programa actual»; **no se borran ni se
   cambian**). La confirmación exige una fecha de vigencia explícita y aceptar ese impacto.
6. **Esquema esperado**: `app/api/sistema.py` y `tests/test_integridad.py` pasan de
   `e6a001` a `f2r001`.

## 5. Cambios en la interfaz

- **Administración › Periodos:** en un periodo cerrado, botón **«Abrir para corrección…»**:
  motivo, plazo (1 a 30 días, sugerido 7) y confirmación escribiendo el nombre del periodo.
- **Barra superior:** junto al periodo activo, un aviso **«Corrigiendo AGOSTO - DICIEMBRE
  2026 · vence el 12/12/2026»**, con el botón **«Terminar corrección»** (solo administrador).
- **Horarios › Por docente** e **Importar horarios:** el periodo reabierto aparece como
  «(abierto para corrección)» y se puede elegir; al confirmar se muestra el impacto.
- **Registro de cambios:** reaperturas y cierres con motivo, usuario y fecha.
- **Rol consulta:** ve el aviso y el historial, sin botones.

## 6. Riesgos y cómo se controlan

| Riesgo | Control |
|---|---|
| Cambiar un horario pasado altera la programación de fechas ya cerradas | Vigencia explícita obligatoria; vista previa de impacto; las asistencias registradas no cambian (son copias) y las que dejan de estar programadas se muestran aparte |
| Olvidar cerrar la reapertura | Plazo obligatorio (≤ 30 días) y cierre automático al vencer; aviso permanente en la barra superior |
| Abuso o cambios sin control | Solo `periodos.gestionar`; motivo obligatorio; auditoría y tabla inmutable |
| Dos reaperturas simultáneas del mismo periodo | Índice único parcial en la base |
| Un camino del código que siga bloqueando o permitiendo de más | Una única función `admite_cambios` usada por los tres servicios; pruebas por cada camino |
| Clientes Windows con versión anterior | El servidor rechaza escrituras igual que hoy; los clientes viejos solo no ven el aviso. Se publica un instalador nuevo junto con la migración |
| Migración en el servidor real | Solo aditiva; antes, `./asi.sh respaldar` y `./asi.sh verificar`; se ensaya completa en la base de pruebas y en la demostración ficticia |
| Reportes de un semestre corregido | Se generan con los datos vigentes al momento; el historial de cambios explica cualquier diferencia con un reporte anterior |

## 7. Pruebas previstas (todas con datos ficticios, solo en `asi_archivo_pytest`)

**Migración**
- `upgrade` y `downgrade` en una base vacía y en una con datos ficticios; los conteos de
  todas las tablas existentes no cambian.
- El disparador impide borrar y modificar una reapertura, y permite cerrarla una sola vez.
- El índice impide dos reaperturas abiertas del mismo periodo.

**Servicio y API**
- Reabrir exige motivo (≥ 15), plazo válido, periodo cerrado y permiso (403 para consulta).
- Con la reapertura vigente: se crea y confirma un horario del periodo anterior **y**, en la
  misma prueba, se registra asistencia de hoy en el periodo activo.
- Al vencer el plazo: escribir en el periodo reabierto vuelve a dar 409 y el historial
  muestra «Venció el plazo».
- Terminar manualmente: igual que vencer, con el motivo del usuario.
- Las asistencias registradas antes de reabrir conservan sus valores exactos después de
  confirmar un horario nuevo (comparación campo por campo).
- `/horarios/{id}/impacto` cuenta bien las horas nuevas pendientes y las capturas que
  quedan fuera del programa.
- Las tres rutas de escritura (horarios, bitácora, importación) respetan la misma regla.

**Interfaz**
- El botón solo aparece en periodos cerrados y para el administrador.
- El aviso de la barra superior aparece y desaparece; el rol de consulta lo ve sin botones.
- El asistente de importación permite elegir el periodo reabierto.

**Instalación**
- Validación del servidor en GitHub (`validar-servidor.sh`) con la migración aplicada.
- Respaldo antes y restauración después, comprobando el historial de reaperturas.

## 8. Plan de implementación (cuando se autorice)

1. Rama nueva desde `entrega-v1` (después de los PR #9 y #10).
2. Copiar el borrador a `server/migrations/versions/` y probarlo **solo** en la base de pruebas.
3. Servicio, endpoints y regla única `admite_cambios`, con sus pruebas.
4. Interfaz (Periodos, barra superior, impacto al confirmar).
5. Revisión visual y PR sin merge.
6. Aplicación en el servidor real solo con autorización de TI y de la Jefatura, después de
   respaldar y verificar.

## 9. Decisiones pendientes

1. ¿El plazo máximo de 30 días y el sugerido de 7 están bien?
2. ¿Corregir **asistencias** del periodo reabierto también se permite, o solo horarios?
   (El diseño lo permite; puede limitarse a horarios sin cambiar la migración.)
