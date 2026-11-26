from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Copy local MEDIA_ROOT files into the configured remote media storage without deleting local files.'

    def handle(self, *args, **options):
        if not settings.R2_CONFIGURED or not default_storage.__class__.__module__.startswith('storages.backends.s3'):
            raise CommandError('Configure all R2 environment variables before migrating local media.')

        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_dir():
            self.stdout.write(self.style.WARNING(f'No local media directory found at {media_root}.'))
            return

        copied = 0
        skipped = 0
        failed = 0
        for source_path in media_root.rglob('*'):
            if not source_path.is_file():
                continue
            object_name = source_path.relative_to(media_root).as_posix()
            try:
                if default_storage.exists(object_name):
                    skipped += 1
                    continue
                with source_path.open('rb') as source:
                    default_storage.save(object_name, File(source, name=object_name))
                copied += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f'Could not copy {object_name}: {exc}'))

        self.stdout.write(self.style.SUCCESS(f'Copied {copied} file(s); skipped {skipped} existing file(s); failed {failed}.'))
        if failed:
            raise CommandError('Some media files could not be copied. Local files were left in place.')
