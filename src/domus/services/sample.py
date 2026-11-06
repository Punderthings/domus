"""The sample home dataset (``examples/sample-home``), loadable from the web interface.

The dataset is a partial export with fixed ids, so it always describes the same
property. Loading it merges it in with the normal importer, which upserts by id
and never touches accounts.
"""

from pathlib import Path

from sqlalchemy import Engine

from domus.backup import BackupError, ImportReport, import_source, open_source, verify
from domus.backup.manifest import MANIFEST_NAME, parse_manifest
from domus.config import Settings

# Where the dataset sits in a source checkout: <repo>/examples/sample-home.
CHECKOUT_DIR = Path(__file__).resolve().parents[3] / "examples" / "sample-home"


class SampleDataError(Exception):
    """The sample dataset is missing or can't be imported."""


def sample_dir(settings: Settings) -> Path | None:
    """The sample dataset folder, or None when this install doesn't ship one."""
    candidate = settings.sample_data_dir or CHECKOUT_DIR
    return candidate if (candidate / MANIFEST_NAME).is_file() else None


def sample_property_id(path: Path) -> str:
    """The id of the one property the dataset describes."""
    try:
        manifest = parse_manifest((path / MANIFEST_NAME).read_bytes())
    except (OSError, BackupError) as exc:
        raise SampleDataError(f"cannot read the sample dataset: {exc}") from exc
    if len(manifest.property_ids) != 1:
        raise SampleDataError("the sample dataset must describe exactly one property")
    return manifest.property_ids[0]


def load_sample(engine: Engine, path: Path, settings: Settings) -> ImportReport:
    """Verify the dataset, then merge it into the database in one transaction."""
    try:
        with open_source(path, max_total_bytes=settings.backup_max_bytes) as source:
            checked = verify(source)
            if not checked.ok:
                raise SampleDataError("the sample dataset failed verification")
            return import_source(engine, source)
    except BackupError as exc:
        raise SampleDataError(f"cannot import the sample dataset: {exc}") from exc
