# ASI-ARCHIVO — Manual del administrador y requisitos para TI

Versión 1.0 · Para quien instale y cuide el servidor y las computadoras de Jefatura.

## 1. Cómo funciona

```
 PC Windows 1 ─┐
 PC Windows 2 ─┼── HTTPS (puerto 443) ──▶  Servidor central (siempre encendido)
 Otra PC/Mac  ─┘                              ├─ https     certificado y cifrado (Caddy)
                                              ├─ api       ASI-ARCHIVO + OCR (Tesseract)
                                              ├─ clamav    antivirus de documentos
                                              ├─ db        base de datos (PostgreSQL 17)
                                              └─ respaldos copia diaria verificada
```

Las computadoras de Jefatura **solo** tienen la aplicación (no necesitan Python,
PostgreSQL ni Tesseract). Todos los datos viven en el servidor. Si una PC se descompone,
no se pierde nada: se instala la aplicación en otra.

## 2. Lo que necesita el área de TI

| Requisito | Detalle |
|---|---|
| Equipo | Servidor, máquina virtual o PC dedicada que **permanezca encendida**. Linux (Ubuntu 22.04/24.04 o Debian 12) recomendado |
| Recursos | 2 núcleos, **4 GB de RAM** (el antivirus usa ~1.5 GB), 40 GB de disco (+ espacio para respaldos) |
| Software | Docker Engine 24+ con Docker Compose v2 (`docker compose version`) |
| Red | Dirección IP fija o nombre DNS interno. Las PCs de Jefatura deben llegar al **puerto 443** (y 80) del servidor |
| Internet de salida | Para descargar imágenes de Docker al instalar y firmas del antivirus (ClamAV). No se envían datos a internet |
| Acceso remoto (opcional) | Para usarlo fuera del campus: VPN institucional. **No** publicar el servidor en internet sin autorización |
| Respaldos externos | Una carpeta de red o disco donde copiar `servidor/respaldos/` (sección 7) |

Datos personales: el servidor guarda información de docentes. Debe quedar en
infraestructura autorizada por la institución y con acceso solo del personal de TI.

## 3. Instalación del servidor (una sola vez)

En el servidor, con un usuario que pueda usar Docker:

```bash
git clone https://github.com/Chavez-Yaritza-02/ASI-ARCHIVO.git
cd ASI-ARCHIVO
git checkout entrega-v1
cd servidor
./asi.sh preparar      # pide nombre/IP del servidor y tipo de certificado
./asi.sh instalar      # pide escribir INSTALAR_NUEVO
```

1. **preparar** pregunta el **nombre o IP** con el que llegarán las PCs (p. ej.
   `192.168.10.25` o `asi-archivo.zapopan.tecmm.edu.mx`) y el **certificado**: `internal`
   (red interna, recomendado) o un correo (dominio público con Let's Encrypt). Crea
   `servidor/.env` (configuración) y `servidor/.secretos/` (contraseñas aleatorias de la
   base de datos, de las sesiones y de los respaldos). **No compartas ni copies estos
   archivos**, salvo la clave de respaldos (paso 4).
2. **instalar** construye los servicios, crea la base de datos con usuarios de permisos
   mínimos, aplica el esquema y deja todo funcionando. Se niega a correr si ya existe una
   instalación (no sobrescribe datos).
3. Crea el primer administrador:
   `./asi.sh usuarios crear-usuario --correo tu@tecmm.edu.mx --nombre "Tu Nombre" --rol administrador`
4. **Guarda la clave de recuperación de respaldos** fuera del servidor:
   `cat .secretos/backup_password` → cópiala en un lugar seguro (sobre cerrado, gestor de
   contraseñas institucional). **Sin ella los respaldos cifrados no se pueden abrir.**
5. Habilita los respaldos: edita `servidor/.env`, cambia `ASI_RESPALDOS_HABILITADOS=SI`,
   ejecuta `docker compose up -d` y comprueba con `./asi.sh respaldar` y `./asi.sh verificar`.

Comprobar: `./asi.sh estado` (todos en `running` / `healthy`). El antivirus descarga sus
firmas la primera vez (5–10 minutos); mientras tanto no se pueden cargar documentos.
Los servicios se reinician solos si el servidor se reinicia.

### Certificado (modo `internal`)

```bash
./asi.sh certificado
```

Crea `servidor/certificado/ASI-ARCHIVO-raiz.crt`. Debe instalarse en cada PC como
**Entidad de certificación raíz de confianza**:
- Por TI para todas las PCs: directiva de grupo (GPO) de certificados raíz.
- O en cada PC (sin permisos de administrador): doble clic en el `.crt` → Instalar
  certificado → Usuario actual → almacén **Entidades de certificación raíz de confianza**
  (pasos detallados en el Manual de uso, sección 9). En PowerShell:
  `Import-Certificate -FilePath ASI-ARCHIVO-raiz.crt -CertStoreLocation Cert:\CurrentUser\Root`
  Windows mostrará una **advertencia de seguridad**; compara la huella con la que te dio TI
  y pulsa **Sí**.

El certificado raíz no contiene datos de la Jefatura; la clave privada nunca sale del
servidor.

## 4. Instalación en las computadoras Windows

1. Descarga el instalador: GitHub → repositorio → **Actions** → flujo **Instalador
   Windows** (rama `entrega-v1`) → última ejecución exitosa → artefacto
   **ASI-ARCHIVO-Windows-x64** (zip con `ASI-ARCHIVO-1.0.0-Windows-x64.exe` y
   `SHA256SUMS.txt`). Los artefactos se guardan 30 días; para generar uno nuevo:
   **Actions → Instalador Windows → Run workflow**.
2. Copia el `.exe` a cada PC y sigue el Manual de uso, sección 1. Requiere Windows 10
   (22H2) u 11 de 64 bits. Se instala por usuario, sin permisos de administrador.
3. Instala el certificado (sección 3) si usas el modo `internal`.
4. Primera conexión: dirección `https://<nombre-o-IP-del-servidor>`.

Comprobar la integridad del instalador (opcional, PowerShell):
`Get-FileHash .\ASI-ARCHIVO-1.0.0-Windows-x64.exe` debe coincidir con `SHA256SUMS.txt`.

## 5. Usuarios

```bash
./asi.sh usuarios listar-usuarios
./asi.sh usuarios crear-usuario --correo persona@tecmm.edu.mx --nombre "Nombre Apellido" --rol consulta
./asi.sh usuarios restablecer-contrasena --correo persona@tecmm.edu.mx
./asi.sh usuarios desactivar-usuario --correo persona@tecmm.edu.mx
./asi.sh usuarios activar-usuario --correo persona@tecmm.edu.mx
./asi.sh usuarios cambiar-rol --correo persona@tecmm.edu.mx --rol administrador
```

| Rol | Puede |
|---|---|
| `administrador` | Todo: horarios, importación, asistencia y correcciones, documentos, reportes |
| `consulta` | Ver horarios, docentes, bitácora, asistencia y documentos; no modifica |

- Las contraseñas se escriben en pantalla (mínimo 10 caracteres); nunca en la línea de
  comandos. Entrégalas a la persona en privado y pídele que no la comparta.
- **Al irse alguien de la Jefatura: desactívalo** (no se borra, para conservar quién hizo
  cada registro). Desactivar corta también las sesiones abiertas.
- Los usuarios no se borran; todo queda en la auditoría.

## 6. Respaldos

Con `ASI_RESPALDOS_HABILITADOS=SI`, **todos los días a las 02:30** (`ASI_HORA_RESPALDO`) se
crea un respaldo **cifrado** (restic) en `servidor/respaldos/cifrado/` con:
- la base de datos completa, tomada en un instante consistente;
- todos los documentos, comprobando la huella SHA-256 de cada uno al copiarlo;
- un manifiesto con el esquema y el número de registros de cada tabla.

Después de crearlo, se comprueba la integridad de todo el repositorio (`restic check`).

| Comando | Qué hace |
|---|---|
| `./asi.sh respaldar` | Respaldo inmediato (además del automático) |
| `./asi.sh respaldos` | Lista de respaldos con su identificador (ID) y fecha |
| `./asi.sh verificar [ID]` | Restaura el respaldo (el último si no se indica) en una base **aislada y temporal** y comprueba esquema, registros de cada tabla y la huella de cada documento. No toca la base en uso |
| `./asi.sh estado` | Incluye el resultado del último respaldo |

**Copia fuera del servidor (indispensable):** un respaldo en el mismo disco no protege
contra fallas del disco. TI debe copiar diariamente `servidor/respaldos/cifrado/` a otro
equipo o carpeta de red autorizada, p. ej.:
`rsync -a /ruta/ASI-ARCHIVO/servidor/respaldos/cifrado/ /mnt/respaldos-asi/`.
Está cifrado: sin la clave de recuperación no se puede leer. Recomendado: una vez al mes,
`./asi.sh verificar`.

## 7. Recuperación

### Volver a los datos de un respaldo

```bash
./asi.sh respaldos                 # elige el ID, p. ej. 3fa1c2d4
./asi.sh restaurar 3fa1c2d4        # pide escribir RESTAURAR
```

1. **Verifica** el respaldo en una base aislada; si falla, no se toca nada.
2. Crea un **respaldo de seguridad del estado actual** (por si eliges el respaldo equivocado).
3. Detiene la aplicación, reemplaza la base y los documentos, vuelve a aplicar los permisos
   mínimos y comprueba la huella de cada documento restaurado.
4. Inicia de nuevo los servicios.

Lo registrado después del respaldo elegido se pierde (queda en el respaldo del paso 2).

### El servidor se descompuso

1. Prepara otro servidor (sección 2) e instala (sección 3, pasos 1–2) con el **mismo
   nombre o IP**.
2. Sustituye `servidor/.secretos/backup_password` por la **clave de recuperación**
   guardada (mismo contenido, una línea) y copia el respaldo externo a
   `servidor/respaldos/cifrado/`.
3. `./asi.sh respaldos` y `./asi.sh restaurar <ID>`.
4. Si el certificado es `internal`, el servidor nuevo tiene otro: `./asi.sh certificado`
   e instálalo en las PCs.

Las cuentas de usuario están en la base de datos: se recuperan con el respaldo.

## 8. Mantenimiento

| Tarea | Cómo |
|---|---|
| ¿Funciona? | `./asi.sh estado` |
| Ver errores | `./asi.sh registros` o `./asi.sh registros api` |
| Reiniciar | `docker compose restart` (dentro de `servidor/`) |
| Actualizar a una versión nueva | 1) `./asi.sh respaldar` y `./asi.sh verificar`; 2) `git pull`; 3) `docker compose build`; 4) `docker compose --profile mantenimiento run --rm migracion`; 5) `docker compose exec -T db psql -U asi_admin -d asi_archivo -v ON_ERROR_STOP=1 < db/permisos.sql`; 6) `docker compose up -d` |
| Actualizar el sistema operativo | Normal; los servicios vuelven a iniciar solos |
| Cambiar hora de respaldo | Editar `ASI_HORA_RESPALDO` en `.env` y `docker compose up -d` |

## 9. Seguridad aplicada

- Solo HTTPS; la base de datos y la API no se exponen fuera del servidor.
- Contraseñas con Argon2; bloqueo de 15 minutos tras 10 intentos fallidos por IP.
- Permisos por rol verificados en el servidor; auditoría inmutable de cada cambio.
- Documentos analizados con antivirus antes de guardarse; sin borrado definitivo.
- Claves aleatorias en `servidor/.secretos/` (entregadas a cada servicio como secretos de
  Docker, no como variables visibles); nunca se suben al repositorio.
- La aplicación se conecta con un usuario de base de datos sin permisos para borrar la
  auditoría ni las versiones de documentos; los respaldos usan un usuario de solo lectura.
- Al restablecer la contraseña o desactivar a alguien, sus sesiones abiertas se cierran.
- En producción la API rechaza iniciar si falta el antivirus, si la clave es débil o si no
  hay nombre de servidor definido.

## 10. Demostración en una computadora de prueba (sin servidor institucional)

Mientras TI prepara el servidor, se puede probar todo en cualquier computadora con Docker,
**solo con datos ficticios**: igual que la sección 3, usando `localhost` como nombre. Si
los puertos 443/80 están ocupados o requieren permisos, cambia en `.env`
`ASI_PUERTO_HTTPS=8443`, `ASI_PUERTO_HTTP=8080` y `ASI_ESCUCHAR=127.0.0.1` (solo esa
computadora) y usa `https://localhost:8443`.

La prueba de aceptación recorre todas las funciones (inicio de sesión, docentes, OCR de un
horario ficticio, asistencia por hora, reportes PDF/Excel, documentos con antivirus y
permisos del rol consulta). Solo corre si en `.env` está `ASI_INSTANCIA_ACEPTACION=true`
(**nunca en el servidor real**, donde debe quedar en `false`) y si el servidor está vacío:
se ejecuta **una sola vez, en un servidor recién instalado**. Crea antes dos usuarios ficticios
(`./asi.sh usuarios crear-usuario ...`, uno administrador y uno consulta) y exporta el
certificado con `./asi.sh certificado`. Desde la carpeta del repositorio:

```bash
uv run python herramientas/aceptacion_servidor.py --url https://localhost:8443 \
    --certificado servidor/certificado/ASI-ARCHIVO-raiz.crt \
    --admin admin@prueba.local --consulta consulta@prueba.local --confirmo-servidor-de-prueba
```

Debe terminar con `ACEPTACIÓN COMPLETA: 17 comprobaciones aprobadas`. Para repetirla,
borra la demostración (`docker compose -p asi-archivo down -v`, **solo en la computadora
de prueba**) y vuelve a instalar.
