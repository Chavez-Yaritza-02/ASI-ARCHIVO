#!/bin/bash
# Restauración de un respaldo cifrado sobre la base y los documentos del servidor.
# Solo la invoca "./asi.sh restaurar", que antes VERIFICA el respaldo en una base aislada,
# crea un respaldo del estado actual y pide confirmación escrita.
set -euo pipefail
umask 077
[ "${PGHOST:-}" = db ] && [ "${PGDATABASE:-}" = asi_archivo ] && [ "${PGUSER:-}" = asi_admin ] \
  || { echo 'Destino de restauración no autorizado'; exit 2; }
respaldo="${1:?Indica el respaldo}"
[[ "$respaldo" =~ ^[a-f0-9]{8,64}$ ]] || { echo 'Identificador inseguro'; exit 2; }
export PGPASSWORD="$(cat /run/secrets/db_admin)"
trabajo=$(mktemp -d /trabajo/restauracion.XXXXXX)
trap 'rm -rf -- "$trabajo"' EXIT

restic --no-lock restore "$respaldo" --tag asi-archivo --target "$trabajo"
mapfile -t encontrados < <(find "$trabajo" -name manifiesto.json -type f)
[ "${#encontrados[@]}" -eq 1 ] || { echo 'Manifiesto ambiguo o inexistente'; exit 2; }
lote="$(dirname "${encontrados[0]}")"

echo 'Restaurando base de datos...'
psql -X -v ON_ERROR_STOP=1 -q <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = 'asi_archivo' AND pid <> pg_backend_pid();
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT USAGE ON SCHEMA public TO asi_app, asi_respaldo;
SQL
pg_restore --no-owner --no-acl --exit-on-error --dbname=asi_archivo "$lote/base.dump"
# Permisos mínimos, igual que en una instalación nueva.
psql -X -v ON_ERROR_STOP=1 -q <<'SQL'
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO asi_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO asi_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO asi_respaldo;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO asi_respaldo;
SQL
psql -X -v ON_ERROR_STOP=1 -q -f /db/permisos.sql

echo 'Restaurando documentos...'
find /datos/documentos -mindepth 1 -delete
cp -a "$lote/documentos/." /datos/documentos/
chown -R 10001:10001 /datos/documentos
chmod 700 /datos/documentos
find /datos/documentos -type f -exec chmod 600 {} +
python3 - "$lote" <<'PY'
import hashlib, json, sys
from pathlib import Path
lote = Path(sys.argv[1])
for d in json.loads((lote / "manifiesto.json").read_text())["documentos"]:
    with open(Path("/datos/documentos") / d["clave"], "rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != d["sha256"]:
            raise SystemExit("Documento restaurado con huella incorrecta: " + d["clave"])
print("Documentos restaurados con su huella SHA-256 correcta")
PY
echo "Restauración terminada desde el respaldo ${respaldo}"
