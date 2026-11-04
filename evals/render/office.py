"""What the DOCX and XLSX renderers share: fixed authorship and dates, and a zip rewrite that
makes two renders of the same spec byte-identical."""

import re
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

AUTHOR = "Bidwright synthetic corpus"
FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)
FIXED_TIME_NAIVE = datetime(2026, 1, 1)
FIXED_STAMP = FIXED_TIME.strftime("%Y-%m-%dT%H:%M:%SZ")
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_MODIFIED = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")


def fix_modified(core_xml: bytes) -> bytes:
    """Set `dcterms:modified` in a core-properties part to the fixed time.

    openpyxl stamps the current time on every save, after the properties were set.
    """
    return _MODIFIED.sub(rb"\g<1>" + FIXED_STAMP.encode() + rb"\g<2>", core_xml)


def freeze_zip(path: Path, rewrite: Mapping[str, Callable[[bytes], bytes]] = {}) -> None:
    """Rewrite the zip with every entry's date fixed, so its bytes depend on content only.

    `rewrite` maps an entry name to a function applied to that entry's bytes on the way.
    """
    with zipfile.ZipFile(path) as source:
        entries = [(info.filename, source.read(info.filename)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in entries:
            if name in rewrite:
                data = rewrite[name](data)
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            target.writestr(info, data)
