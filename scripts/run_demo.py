"""Demo entry point. Phase 0: load the site config and report what it holds."""

from pathlib import Path

import yaml

SITE_PATH = Path(__file__).resolve().parents[1] / "config" / "site.yaml"


def main() -> None:
    site = yaml.safe_load(SITE_PATH.read_text(encoding="utf-8"))
    print("hello")
    print(
        f"loaded {SITE_PATH.name}: {len(site['stations'])} stations, "
        f"{len(site['pickets'])} pickets, {len(site['zones'])} zones"
    )


if __name__ == "__main__":
    main()
