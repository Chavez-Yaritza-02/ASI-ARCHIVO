#!/bin/bash
# Restauración (dentro del contenedor "restauracion"; lo invoca ../restaurar.sh).
# Reemplaza la base de datos y los documentos por los del respaldo indicado.
set -euo pipefail
respaldo="$1"
dir="/respaldos/${respaldo}"
/scripts/verificar-respaldo.sh "$respaldo"
echo "Restaurando base de datos..."
psql -d postgres -qc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                      WHERE datname = 'asi_archivo' AND pid <> pg_backend_pid()" >/dev/null
dropdb asi_archivo
createdb asi_archivo
pg_restore --no-owner --exit-on-error --dbname=asi_archivo "$dir/base.dump"
echo "Restaurando documentos..."
find /datos/documentos -mindepth 1 -delete
tar -C /datos --numeric-owner -xzpf "$dir/documentos.tar.gz"
chown -R 10001:10001 /datos/documentos
chmod 700 /datos/documentos
echo "Restauración terminada desde ${respaldo}"
