#!/bin/bash
# Descarga las firmas la primera vez, las mantiene actualizadas y arranca el servicio.
set -e
chown -R clamav:clamav /var/lib/clamav
if [ ! -f /var/lib/clamav/main.cvd ] && [ ! -f /var/lib/clamav/main.cld ]; then
  echo "Descargando firmas del antivirus (primera vez)..."
  until freshclam --foreground --stdout; do echo "Reintento en 60 s"; sleep 60; done
fi
freshclam --daemon --checks=12 --stdout
exec clamd --foreground
