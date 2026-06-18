from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    load_env(Path(".env"))
    from price_share_service import RECORDS_HASH, UPSTASH, UPVOTES_HASH

    deleted = UPSTASH.pipeline([["DEL", RECORDS_HASH], ["DEL", UPVOTES_HASH]])
    print(f"cleared realtime redis hashes: {deleted}")


if __name__ == "__main__":
    main()
