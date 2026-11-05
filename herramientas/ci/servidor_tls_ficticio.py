"""Servidor TLS de loopback, sin autenticación, base de datos ni documentos reales."""

import argparse
import json
import ssl
from http.server import BaseHTTPRequestHandler, HTTPServer

from asi_shared.version import PROTOCOLO, VERSION


class Respuesta(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/sistema/identidad":
            self.send_error(404)
            return
        cuerpo = json.dumps(
            {"producto": "ASI-ARCHIVO", "protocolo": PROTOCOLO, "version": VERSION}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--certificado", required=True)
    p.add_argument("--clave", required=True)
    p.add_argument("--puerto", type=int, default=18443)
    a = p.parse_args()
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(a.certificado, a.clave)
    servidor = HTTPServer(("127.0.0.1", a.puerto), Respuesta)
    servidor.socket = contexto.wrap_socket(servidor.socket, server_side=True)
    servidor.serve_forever()
