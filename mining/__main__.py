"""CLI: python -m mining <stage>|run-all [--refresh] [--repo owner/name]"""
from __future__ import annotations

import argparse
import importlib
import time

from . import console

STAGES = {
    "search": "s1_search", "select": "s2_select", "collect": "s3_collect", "extract": "s4_extract",
    "sheets": "s5_coding_sheets", "agreement": "s6_agreement", "analyze": "s7_analyze", "report": "s8_report",
}


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m mining", description=__doc__)
    p.add_argument("stage", choices=[*STAGES, "run-all"])
    p.add_argument("--refresh", action="store_true", help="ignore caches / regenerate outputs")
    p.add_argument("--repo", help="restrict collect/extract to one owner/name")
    a = p.parse_args()
    for stage in (STAGES if a.stage == "run-all" else [a.stage]):
        t = time.time()
        console.rule(f"[bold]{stage}")
        importlib.import_module(f".{STAGES[stage]}", __package__).run(refresh=a.refresh, repo=a.repo)
        console.print(f"[dim]{stage} done in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
