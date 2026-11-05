#!/bin/bash
# Cifrado restic. No elimina respaldos anteriores ni ejecuta retención destructiva.
set -euo pipefail
umask 077
[ "${ASI_RESPALDOS_HABILITADOS:-NO}" = SI ] || { echo 'Respaldos no habilitados por el administrador'; exit 2; }
export PGPASSWORD="$(cat /run/secrets/db_respaldo)"
: "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD_FILE:?}"
# Serializar las capturas, incluyendo las solicitadas manualmente.
exec 9>/respaldos/.respaldo.lock
flock -n 9 || { echo 'Ya hay un respaldo en ejecución'; exit 2; }
trabajo=$(mktemp -d /trabajo/respaldo.XXXXXX)
trap 'rm -rf -- "$trabajo"' EXIT
if [ ! -f "$RESTIC_REPOSITORY/config" ]; then
  [ ! -e "$RESTIC_REPOSITORY" ] || { echo 'Repositorio existente sin configuración: revisión requerida'; exit 2; }
  restic init
fi
python3 /scripts/copia_consistente.py "$trabajo/lote"
# La restauración localiza el lote por su manifiesto; el nombre de equipo fijo agrupa los respaldos.
(cd "$trabajo" && restic backup lote --host asi-archivo --tag asi-archivo --json) > "$trabajo/resultado.jsonl"
restic check --read-data
python3 - "$trabajo/resultado.jsonl" > /respaldos/ULTIMO_RESULTADO.txt <<'PY'
import json,sys
from datetime import datetime, timezone
filas = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
resumen = next(x for x in filas if x.get('message_type')=='summary')
print(json.dumps({'estado':'cifrado_integridad_verificada','snapshot':resumen['snapshot_id'],
                  'fecha_utc':datetime.now(timezone.utc).isoformat()}))
PY
echo 'Respaldo cifrado creado y comprobado. La restauración se prueba por separado.'
