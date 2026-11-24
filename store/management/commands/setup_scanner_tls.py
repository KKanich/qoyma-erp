"""Generate local-only TLS files; never installs a trust root automatically."""
import ipaddress
import os
from pathlib import Path
import shutil
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Generate a local CA and HTTPS certificate for a private LAN IP (requires openssl).'

    def add_arguments(self, parser):
        parser.add_argument('--host', required=True, help='Mac private LAN IPv4 address')

    def handle(self, *args, **options):
        try:
            host = ipaddress.IPv4Address(options['host'])
        except ValueError as exc:
            raise CommandError('Use the Mac LAN IPv4 address.') from exc
        if not host.is_private:
            raise CommandError('This development command only accepts private LAN addresses.')
        openssl = shutil.which('openssl')
        if not openssl:
            raise CommandError('openssl is required.')
        folder = Path(settings.BASE_DIR) / '.scanner-tls'
        folder.mkdir(mode=0o700, exist_ok=True)
        public = folder / 'public'
        public.mkdir(exist_ok=True)
        def run(*arguments):
            subprocess.run([openssl, *arguments], cwd=folder, check=True, capture_output=True)
        old_umask = os.umask(0o077)
        try:
            if not (folder / 'ca.key').exists():
                run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '365',
                    '-keyout', 'ca.key', '-out', 'ca.pem', '-subj', '/CN=Qoyma Local Scanner CA',
                    '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
                    '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
            run('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'server.key', '-out', 'server.csr',
                '-subj', '/CN=Qoyma Local Scanner')
            (folder / 'extensions.cnf').write_text(
                'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
                f'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1,IP:{host}\n')
            run('x509', '-req', '-in', 'server.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key',
                '-CAcreateserial', '-out', 'server.pem', '-days', '30', '-sha256', '-extfile', 'extensions.cnf')
            run('x509', '-in', 'ca.pem', '-outform', 'DER', '-out', 'public/qoyma-local-ca.cer')
        except subprocess.CalledProcessError as exc:
            raise CommandError(exc.stderr.decode(errors='replace')) from exc
        finally:
            os.umask(old_umask)
        self.stdout.write(self.style.SUCCESS(f'Local certificate ready for {host}. No system trust settings changed.'))
        self.stdout.write(f'Phone certificate: {public / "qoyma-local-ca.cer"}')
        self.stdout.write('Install this CA on the phone and enable SSL trust before opening HTTPS.')
