"""python manage.py backup_data  ->  writes a compressed JSON snapshot of all app data into BACKUP_DIR and
keeps only the newest BACKUP_KEEP files. Schedule it daily (cron / Render cron job)."""
import gzip
import io
from datetime import datetime, timezone

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create a gzip JSON backup of the BioSpine data."

    def handle(self, *args, **opts):
        out = io.StringIO()
        call_command("dumpdata", "biospine_app", "--indent", "1", stdout=out)
        folder = settings.BACKUP_DIR
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = folder / f"biospine-{stamp}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(out.getvalue())
        path.chmod(0o600)                                    # contains password hashes: owner-only
        old = sorted(folder.glob("biospine-*.json.gz"))[:-settings.BACKUP_KEEP]
        for f in old:
            f.unlink()
        self.stdout.write(self.style.SUCCESS(f"Backup written: {path} ({path.stat().st_size // 1024} KB). Kept the newest {settings.BACKUP_KEEP}."))
        self.stdout.write("Restore with:  gunzip -c FILE.json.gz > data.json && python manage.py loaddata data.json")
