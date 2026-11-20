"""Select verified public filings and aggregate fund disclosures from the v0.1.0 archive."""

import json
import tarfile
import sys
import re
from hashlib import sha256
from pathlib import PurePosixPath
from equity_evidence.storage import library, save, save_bytes


def import_public(archive):
    with tarfile.open(archive) as t:
        members = {
            m.name: m
            for m in t
            if m.isfile()
            and not any(p.startswith("._") for p in PurePosixPath(m.name).parts)
        }
        selected = {}
        for n, m in members.items():
            if not re.fullmatch(r"\.sisyphus/data/snapshots/[a-f0-9]{32}\.json", n):
                continue
            record = json.load(t.extractfile(m))
            if not record.get("cash_quality"):
                continue
            financial = record["financial"]["data"]
            selected[financial["code"]] = (
                record["cash_quality"],
                financial["periods"][0],
            )
        for code, (report, financial) in selected.items():
            metas = [f["meta"] for f in report["filings"]]
            for meta in metas:
                key = meta["sha256"]
                blob = t.extractfile(
                    members[".sisyphus/data/documents/" + key + ".pdf"]
                ).read()
                if sha256(blob).hexdigest() != key:
                    raise ValueError("原件校验失败")
                save_bytes(library() / "documents" / (key + ".pdf"), blob)
            save(
                library() / "filings" / code / (report["scope"]["end"] + ".json"),
                dict(
                    scope=report["scope"],
                    documents=metas,
                    financial=financial,
                    errors=report["errors"],
                ),
            )
        for n, m in members.items():
            match = re.fullmatch(
                r"\.sisyphus/data/(studies/funds/(?:\d{4}|\d{4}-\d\d-\d\d)/(?:[0-9]{6}|ranking-\d+|study-[a-f0-9]{32})\.json)",
                n,
            )
            if match:
                save(library() / match[1], json.load(t.extractfile(m)))
    print("Imported public disclosure metadata:", sorted(selected))


if __name__ == "__main__":
    import_public(sys.argv[1])
