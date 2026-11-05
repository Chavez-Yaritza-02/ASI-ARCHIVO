#!/bin/bash
set -euo pipefail
umask 077
hora="${ASI_HORA_RESPALDO:-02:30}"
[[ "$hora" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || { echo 'Hora de respaldo inválida'; exit 2; }
if [ "${ASI_RESPALDOS_HABILITADOS:-NO}" != SI ]; then
  echo 'Respaldos automáticos deshabilitados: requieren configuración y autorización.'
  exec sleep infinity
fi
echo "Respaldos cifrados diarios a las $hora"
while true; do
  objetivo=$(date -d "today $hora" +%s)
  ahora=$(date +%s)
  [ "$objetivo" -le "$ahora" ] && objetivo=$(date -d "tomorrow $hora" +%s)
  sleep $((objetivo - ahora))
  if ! /scripts/respaldar.sh; then
    date '+%Y-%m-%d %H:%M:%S RESPALDO FALLIDO: revisar registros' > /respaldos/ULTIMO_RESULTADO.txt
  fi
done
