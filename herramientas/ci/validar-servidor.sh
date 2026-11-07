#!/bin/bash
# SOLO en GitHub Actions: infraestructura nueva, loopback y todos los datos ficticios.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Este escenario solo se ejecuta en CI efímero'; exit 2; }
: "${RUNNER_TEMP:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_WORKSPACE:?}"
raiz=$(mktemp -d "$RUNNER_TEMP/asi-servidor.XXXXXX")
git archive HEAD | tar -x -C "$raiz"
export ASI_PROYECTO="asi-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
export ASI_ESCUCHAR=127.0.0.1 ASI_PUERTO_HTTPS=18443 ASI_PUERTO_HTTP=18080
export ASI_RESPALDOS_HABILITADOS=SI ASI_INSTANCIA_ACEPTACION=true
cd "$raiz/servidor"
DC=(docker compose -p "$ASI_PROYECTO")
limpiar() {
  codigo=$?
  if [ "$codigo" -ne 0 ]; then "${DC[@]}" logs --tail 100 || true; fi
  # Solo recursos NUEVOS del proyecto CI de esta ejecución. Nunca proyectos de usuarios.
  "${DC[@]}" --profile verificacion down -v --remove-orphans || true
}
trap limpiar EXIT
python3 preparar.py --dominio localhost --tls internal
"${DC[@]}" config -q
"${DC[@]}" build api respaldos
"${DC[@]}" up -d --wait --wait-timeout 120 db
"${DC[@]}" --profile mantenimiento run --rm migracion
"${DC[@]}" exec -T db psql -U asi_admin -d asi_archivo -v ON_ERROR_STOP=1 < db/permisos.sql
"${DC[@]}" up -d --wait --wait-timeout 900 api clamav https respaldos
# Caddy genera su certificado interno unos segundos después de arrancar: esperar a que el
# HTTPS responda (con verificación del certificado) antes de las pruebas.
for intento in $(seq 1 30); do
  "${DC[@]}" cp https:/data/caddy/pki/authorities/local/root.crt "$raiz/raiz.crt" 2>/dev/null \
    && curl -sf --cacert "$raiz/raiz.crt" https://localhost:18443/sistema/identidad >/dev/null \
    && break
  [ "$intento" -lt 30 ] || { echo 'HTTPS no estuvo listo en 60 s'; exit 1; }
  sleep 2
done
openssl rand -hex 24 > "$raiz/admin-clave"
openssl rand -hex 24 > "$raiz/consulta-clave"
"${DC[@]}" exec -T api python /opt/asi/entrada.py python -m app.cli crear-usuario --correo admin@example.invalid --nombre 'Administrador ficticio' --rol administrador --contrasena-stdin < "$raiz/admin-clave"
"${DC[@]}" exec -T api python /opt/asi/entrada.py python -m app.cli crear-usuario --correo consulta@example.invalid --nombre 'Consulta ficticia' --rol consulta --contrasena-stdin < "$raiz/consulta-clave"
# El cliente normal valida el certificado; no se utiliza verify=False.
cat "$raiz/admin-clave" "$raiz/consulta-clave" | "$GITHUB_WORKSPACE/.venv/bin/python" "$raiz/herramientas/aceptacion_servidor.py" \
  --url https://localhost:18443 --certificado "$raiz/raiz.crt" \
  --admin admin@example.invalid --consulta consulta@example.invalid --confirmo-servidor-de-prueba
# entrada.py carga la conexión desde los secretos (exec no usa el ENTRYPOINT).
"${DC[@]}" exec -T api python /opt/asi/entrada.py python - <<'PY'
from sqlalchemy import text
from app.db.sesion import obtener_engine
with obtener_engine().connect() as c:
    assert c.execute(text('SELECT current_user')).scalar() == 'asi_app'
    assert not c.execute(text("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user")).scalar()
    for tabla in ('auditoria','documento_version'):
        assert not c.execute(text("SELECT has_table_privilege(current_user,:tabla,'UPDATE')"), {'tabla':tabla}).scalar()
print('Privilegios de la API verificados: rol limitado y auditoría/versiones protegidas')
PY
# La detección EICAR se prueba directamente contra el antivirus real, no con mocks.
"${DC[@]}" exec -T api python - <<'PY'
import subprocess,tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'ficticio-antivirus.txt'
    p.write_bytes(b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$' + b'EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*')
    assert subprocess.run(['/usr/local/bin/asi-antivirus','--',str(p)],capture_output=True).returncode == 1
print('Antivirus real: patrón inofensivo de prueba detectado')
PY
"${DC[@]}" exec -T respaldos /scripts/respaldar.sh
"${DC[@]}" --profile verificacion up -d --wait --wait-timeout 120 db-verificacion
"${DC[@]}" --profile verificacion run --rm -T verificacion </dev/null
# Los servicios internos no deben publicar puertos del host.
for servicio in db api clamav; do
  id=$("${DC[@]}" ps -q "$servicio")
  docker inspect --format '{{json .NetworkSettings.Ports}}' "$id" | python3 -c 'import json,sys; assert not any((json.load(sys.stdin) or {}).values())'
done
printf '%s\n' 'Servidor HTTPS, roles, OCR, horarios, asistencia, PDF/Excel, archivo y recuperación cifrada: correctos'
