"""Shared helpers: repo paths, the parameter file, and turning it into engine / backtest settings."""
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PARAMS_PATH = os.path.join(ROOT, "params", "params.json")
ENGINE_PATH = os.path.join(ROOT, "engine", "engine.js")
ENGINE_KEYS = ["damp", "ret_disc", "env_scale", "expertWeight", "weeklyExpert"]
PARAMS_LINE = re.compile(r"^const PARAMS = \{.*\};$", re.M)

# game-environment elasticities (log change per unit of implied-total change x, and per spread point);
# the same numbers as ENV_K in engine.js
ENV_K = {"att": (0.2378, -0.00353), "pyd": (0.5709, -0.0025), "ptd": (0.6785, -0.00071),
         "car": (-0.0775, 0.00735), "ryd": (0.1785, 0.00615), "rtd": (0.4132, 0.00569)}


def load_params_file(path=None):
    return json.load(open(path or PARAMS_PATH))


def values(pj):
    """{name: value} from a params.json structure."""
    return {k: v["value"] for k, v in pj["params"].items()}


def engine_params(vals):
    return {k: vals[k] for k in ENGINE_KEYS if k in vals}


def engine_source(vals=None, src=None):
    """engine.js with its PARAMS line set from the given values (default: the params file)."""
    src = src if src is not None else open(ENGINE_PATH).read()
    vals = vals if vals is not None else values(load_params_file())
    line = "const PARAMS = " + json.dumps(engine_params(vals), separators=(",", ":")) + ";"
    assert len(PARAMS_LINE.findall(src)) == 1, "engine.js must have exactly one PARAMS line"
    return PARAMS_LINE.sub(lambda m: line, src, count=1)


def backtest_params(vals):
    """Settings for backtest/backtest_core.py that reproduce the live model with these values."""
    g = float(vals.get("env_scale", 1.0))
    env = {"k_usual": 3}
    for k, (xi, si) in ENV_K.items():
        env[k + "_i"], env[k + "_s"] = g * xi, g * si
    K = {k[2:]: float(v) for k, v in vals.items() if k.startswith("K_")}
    return dict(prior_games=vals["prior_games"], prior_moved=vals["prior_moved"], vet_prior=vals["vet_prior"],
                team_prior=vals["team_prior"], w1=vals["w1"], w2=vals["w2"], decay=vals["decay"], K=K,
                env=env if g > 0 else None, low_target=vals["low_target"], damp=vals["damp"],
                ret_disc=vals["ret_disc"], blend2=vals["blend2"], rookie_prior=float(vals.get("rookie_prior", 0.0)))


def esc_script(text, js=False):
    """Text safe inside a <script> element. Data and plain text: every "</" becomes "<\\/" (readers
    un-escape it). JavaScript: only "</script" is touched, so code and template literals stay as written."""
    if js:
        return re.sub(r"</(script)", r"<\\/\1", text, flags=re.I)
    return text.replace("</", "<\\/")


def dump_params(pj, path=None):
    """Write params.json with one parameter per line, so every change is a one-line diff."""
    head = {k: v for k, v in pj.items() if k != "params"}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},")
    lines.append('  "params": {')
    items = list(pj["params"].items())
    w = max(len(k) for k, _ in items) + 3
    for i, (k, v) in enumerate(items):
        key = (json.dumps(k) + ":").ljust(w)
        lines.append(f"    {key}{json.dumps(v, ensure_ascii=False)}{',' if i < len(items) - 1 else ''}")
    lines += ["  }", "}"]
    open(path or PARAMS_PATH, "w").write("\n".join(lines) + "\n")
