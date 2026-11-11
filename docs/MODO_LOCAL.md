# Modo local (una sola computadora)

Desde la rama `modo-local`, ASI-ARCHIVO funciona **sin servidor aparte**, igual que una
aplicación de escritorio común: se instala con un solo archivo y guarda todo en la misma
computadora.

## Cómo funciona

- Al abrirse, la aplicación arranca por dentro la misma API del servidor central, solo
  accesible desde esa computadora (`127.0.0.1`, puerto elegido al azar).
- La base de datos es **SQLite** (un archivo), no PostgreSQL.
- Los documentos se analizan con **Microsoft Defender** si está disponible.
- El lector de PDF (**Tesseract**, español e inglés) viene dentro del instalador.

## Dónde quedan los datos

| Sistema | Carpeta |
|---|---|
| Windows | `C:\ASI-ARCHIVO-DATOS` |
| macOS / Linux | `~/ASI-ARCHIVO-DATOS` |

Se puede cambiar con la variable de entorno `ASI_DATOS`. La carpeta está fuera de
Documentos y Escritorio a propósito: OneDrive los sincroniza y una base de datos
sincronizada mientras está abierta se puede dañar.

```
ASI-ARCHIVO-DATOS/
├── asi.db             maestros, horarios, asistencias, usuarios, auditoría
├── documentos/        PDF e imágenes del archivo digital
└── .clave-sesiones    clave para firmar las sesiones (se crea sola)
```

Desinstalar la aplicación **no borra** esta carpeta.

## Primer uso

La primera vez aparece la ventana **Bienvenida**: se crea la cuenta de administrador
(contraseña de 10 caracteres o más). Después se entra con esa cuenta.

## Respaldos

**Configuración › Respaldos**:

- **Hacer respaldo…**: crea `ASI-ARCHIVO-respaldo-AAAA-MM-DD-HHMM.zip` en la carpeta
  elegida (USB, Google Drive). La copia de la base es consistente aunque la aplicación esté
  abierta, y el .zip se verifica antes de darlo por bueno.
- **Restaurar un respaldo…**: se aplica la próxima vez que se abre la aplicación. Los datos
  actuales no se borran: se mueven a `ASI-ARCHIVO-DATOS-antes-de-restaurar-<fecha>`.

Recomendación: un respaldo por semana como mínimo, guardado fuera de la computadora.

## Usar el servidor central (avanzado)

`ASI-ARCHIVO.exe --servidor` (o definir `ASI_SERVIDOR_URL`) conserva el funcionamiento
anterior con servidor PostgreSQL. En el menú Inicio: «Conectar a un servidor central».

## Desarrollo

```bash
uv run asi-archivo                      # modo local (datos en ~/ASI-ARCHIVO-DATOS)
ASI_DATOS=/tmp/prueba uv run asi-archivo  # modo local con otra carpeta
uv run asi-archivo --servidor           # con la API en otra terminal, como antes
uv run pytest -q client/tests/test_modo_local.py
```

Detalles técnicos:

- `server/app/local.py` crea las tablas desde los modelos y carga los mismos datos
  iniciales (roles, permisos, categorías, tolerancia) y protecciones (auditoría inmutable,
  archivo sin borrado) que dejan las migraciones de PostgreSQL. **Si una migración nueva
  agrega permisos o datos iniciales, agrégalos también ahí.**
- `FechaHora` (en `models/base.py`) guarda fechas en UTC en SQLite y las devuelve con zona.
- La restricción de duración de `asistencia_hora` tiene una versión por motor.
- En el `.exe`, el procesador aislado de documentos es el mismo ejecutable con
  `--procesar-archivo`.
- `--autoprueba-local` comprueba el `.exe` instalado (lo ejecuta GitHub Actions).
