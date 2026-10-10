"""Assemble the Fantasy Trader page from the repo.

    python3 tools/make_page.py --db db.json --injnews injury_news.json --out fantasy-trader.html

page/template.html + engine/engine.js (PARAMS line from params/params.json) + page/ui.js, with the week's
data (db.json, injury_news.json), and the builder, runbook and parameter file embedded as fallbacks.
The output is the page source to publish (Artifact publish with url = the live page).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ftlib import ROOT, engine_source, esc_script, load_params_file, values  # noqa: E402


def build(db_text, injnews_text, params_path=None):
    pj = load_params_file(params_path)
    tpl = open(os.path.join(ROOT, "page", "template.html")).read()
    parts = {
        "DB": esc_script(db_text.strip()),
        "INJNEWS": esc_script(injnews_text.strip()),
        "BUILDER": esc_script(open(os.path.join(ROOT, "pipeline", "build_db.py")).read()),
        "PARAMS": esc_script(json.dumps(pj, indent=1)),
        "RUNBOOK": esc_script(open(os.path.join(ROOT, "runbooks", "weekly.md")).read()),
        "ENGINE": esc_script(engine_source(values(pj)), js=True),
        "UI": esc_script(open(os.path.join(ROOT, "page", "ui.js")).read(), js=True),
    }
    out = tpl
    for k, v in parts.items():
        ph = "{{" + k + "}}"
        assert out.count(ph) == 1, ph
        out = out.replace(ph, v)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--injnews", required=True)
    ap.add_argument("--params", default=None)
    ap.add_argument("--out", default="fantasy-trader.html")
    a = ap.parse_args()
    html = build(open(a.db).read(), open(a.injnews).read(), a.params)
    open(a.out, "w").write(html)
    print(f"wrote {a.out} ({len(html) // 1024} KB)")
