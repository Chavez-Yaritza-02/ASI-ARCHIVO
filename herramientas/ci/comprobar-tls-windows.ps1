# Solo en runner efímero: CA ficticia y servidor loopback; no toca certificados de usuarios.
param([Parameter(Mandatory=$true)][string]$Ejecutable)
$ErrorActionPreference = 'Stop'
$trabajo = Join-Path $env:RUNNER_TEMP 'asi-tls-ficticio'
New-Item -ItemType Directory -Path $trabajo | Out-Null
$openssl = 'C:\Program Files\Git\usr\bin\openssl.exe'
$cert = Join-Path $trabajo 'ficticio.crt'
$clave = Join-Path $trabajo 'ficticio.key'
& $openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 -keyout $clave -out $cert -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost' -addext 'basicConstraints=critical,CA:TRUE' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar el certificado ficticio' }
$python = (Resolve-Path '.venv-instalador/Scripts/python.exe').Path
$servicio = Start-Process $python -ArgumentList @('herramientas/ci/servidor_tls_ficticio.py','--certificado',$cert,'--clave',$clave) -PassThru
$importado = $null
try {
  Start-Sleep -Seconds 2
  function Comprobar([string]$Nombre,[string]$Url,[int]$Esperado) {
    $r = Join-Path $trabajo ($Nombre+'.json')
    $p = Start-Process $Ejecutable -ArgumentList @('--comprobar-tls','--servidor',$Url,'--resultado',$r) -PassThru
    if (-not $p.WaitForExit(30000)) { $p.Kill(); throw 'Timeout del cliente TLS' }
    if ($p.ExitCode -ne $Esperado) { throw "Resultado TLS incorrecto: $Nombre" }
  }
  Comprobar 'sin-confianza' 'https://localhost:18443' 2
  # LocalMachine: CurrentUser\Root abre un diálogo de confirmación que bloquea el runner.
  $importado = Import-Certificate -FilePath $cert -CertStoreLocation Cert:\LocalMachine\Root
  Comprobar 'con-confianza' 'https://localhost:18443' 0
  Comprobar 'nombre-incorrecto' 'https://127.0.0.1:18443' 2
  '{"tls_real":true,"no_confiable_rechazado":true,"confiable_aceptado":true,"nombre_incorrecto_rechazado":true}' | Set-Content dist/instalador/tls-windows.json
} finally {
  if ($importado) { Remove-Item ("Cert:\LocalMachine\Root\"+$importado.Thumbprint) }
  Stop-Process -Id $servicio.Id -ErrorAction SilentlyContinue
}
