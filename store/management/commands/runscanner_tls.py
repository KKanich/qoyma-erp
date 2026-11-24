"""Development HTTPS server for camera testing on the local network."""
import ssl
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import Command as RunServer
from django.core.management.base import CommandError
from django.core.servers.basehttp import WSGIServer


class Command(RunServer):
    help = 'Run local development HTTPS after setup_scanner_tls. Not a production server.'
    protocol = 'https'

    def get_handler(self, *args, **options):
        # Serve local assets even if the normal application runs with DEBUG=False.
        options['insecure_serving'] = True
        return super().get_handler(*args, **options)

    def inner_run(self, *args, **options):
        folder = Path(settings.BASE_DIR) / '.scanner-tls'
        if not (folder / 'server.pem').exists():
            raise CommandError('Run setup_scanner_tls --host <LAN-IP> first.')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(folder / 'server.pem', folder / 'server.key')

        class LocalTLSServer(WSGIServer):
            def server_bind(self):
                super().server_bind()
                self.socket = context.wrap_socket(self.socket, server_side=True)

        self.server_cls = LocalTLSServer
        return super().inner_run(*args, **options)
