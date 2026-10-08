"""Daily local recovery snapshots, created by the sole publication worker."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

from app.config import REPO_ROOT
from app.csv_store import storage_lock


def create_backup() -> str | None:
    configured = os.environ.get('BACKUP_ROOT')
    if not configured:
        return None
    destination = Path(configured)
    destination.mkdir(parents=True, exist_ok=True)
    name = 'diary-' + datetime.now(timezone.utc).strftime('%Y-%m-%d') + '.tar.gz'
    final = destination / name
    if not final.exists():
        with storage_lock:
            fd, temporary = tempfile.mkstemp(prefix='.backup-', dir=destination)
            os.close(fd)
            try:
                manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'csv_sha256': {}}
                for path in sorted((REPO_ROOT / 'data').glob('*.csv')):
                    manifest['csv_sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                payload = json.dumps(manifest, indent=2).encode()
                with tarfile.open(temporary, 'w:gz') as archive:
                    # Restore the index/history alongside local CSVs, including unpublished saves.
                    archive.add(REPO_ROOT / 'data', arcname='repo/data')
                    archive.add(REPO_ROOT / '.git', arcname='repo/.git')
                    info = tarfile.TarInfo('backup-manifest.json')
                    info.size = len(payload)
                    info.mode = 0o600
                    archive.addfile(info, io.BytesIO(payload))
                with open(temporary, 'rb') as handle:
                    os.fsync(handle.fileno())
                os.replace(temporary, final)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        for old in sorted(destination.glob('diary-????-??-??.tar.gz'), reverse=True)[14:]:
            old.unlink()
    return datetime.fromtimestamp(final.stat().st_mtime, timezone.utc).isoformat()
