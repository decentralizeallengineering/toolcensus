"""toolcensus: count how an agent calls its tools, then check whether another tool set would accept those calls.

census: reads Claude Code style session records (JSONL; assistant messages with tool_use blocks) and keeps only
tool names, argument names and value types. It never keeps, prints or stores an argument value.
check: compares each recorded call shape with a schema file for a different tool set and reports, by call count,
how many shapes are accepted as they are, accepted with an argument that has no effect, or rejected.

Schema file (JSON):
  {"unknown_args": "reject",                       # or "ignore": an argument the tool does not list has no effect
   "tools": {"Read": {"args": {"file_path": "str", "offset": "int"}, "required": ["file_path"],
                      "aliases": {"path": "file_path"}}}}
Types: str int float number bool list dict null any. "number" takes int and float.
"""
import json
import os
from collections import Counter, defaultdict

__version__ = "0.1.0"


def _tname(v):
    return "null" if v is None else type(v).__name__


def find_files(paths, max_files=40, max_bytes=20 * 1024 * 1024):
    """Newest first, files over max_bytes skipped, at most max_files."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for d, _, fs in os.walk(p):
                out += [os.path.join(d, f) for f in fs if f.endswith(".jsonl")]
        elif os.path.isfile(p):
            out.append(p)
    out = [f for f in out if os.path.getsize(f) <= max_bytes]
    out.sort(key=os.path.getmtime, reverse=True)
    return out[:max_files]


def census(files, tools=None):
    calls, args, sets = Counter(), defaultdict(Counter), Counter()
    for f in files:
        with open(f, errors="replace") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                m = e.get("message") if isinstance(e, dict) else None
                c = m.get("content") if isinstance(m, dict) else None
                if e.get("type") != "assistant" or not isinstance(c, list):
                    continue
                for b in c:
                    if not isinstance(b, dict) or b.get("type") != "tool_use" or not isinstance(b.get("name"), str):
                        continue
                    if tools and b["name"] not in tools:
                        continue
                    n, i = b["name"], b.get("input")
                    i = i if isinstance(i, dict) else {}
                    calls[n] += 1
                    for k in i:
                        args[n][k] += 1
                    sets[(n, tuple(sorted((k, _tname(v)) for k, v in i.items())))] += 1
    return {
        "files": len(files),
        "calls": dict(calls),
        "args": {n: dict(a) for n, a in args.items()},
        "sets": [{"tool": t, "args": [list(x) for x in s], "count": c} for (t, s), c in sets.most_common()],
    }


def _type_ok(want, have):
    return want == "any" or want == have or (want == "number" and have in ("int", "float")) or (want == "float" and have == "int")


def classify(shape, schema):
    """shape: {"tool", "args": [[name, type], ...]}. Returns (class, reason): ok, ignored or rejected."""
    spec = schema.get("tools", {}).get(shape["tool"])
    if spec is None:
        return "rejected", "unknown tool"
    known, aliases = spec.get("args", {}), spec.get("aliases", {})
    seen, extra = set(), []
    for name, typ in shape["args"]:
        real = name if name in known else aliases.get(name)
        if real is None:
            extra.append(name)
        elif not _type_ok(known[real], typ):
            return "rejected", f"argument {name} is {typ}, tool wants {known[real]}"
        else:
            seen.add(real)
    missing = [r for r in spec.get("required", []) if r not in seen]
    if missing:
        return "rejected", "missing " + ",".join(missing)
    if extra:
        if schema.get("unknown_args", "reject") == "ignore":
            return "ignored", "no effect: " + ",".join(extra)
        return "rejected", "unknown argument " + ",".join(extra)
    return "ok", ""


def check(cen, schema):
    rows, total = [], Counter()
    for s in cen["sets"]:
        c, why = classify(s, schema)
        total[c] += s["count"]
        rows.append({"tool": s["tool"], "args": [a[0] for a in s["args"]], "count": s["count"], "class": c, "why": why})
    n = sum(total.values())
    return {"calls": n, "ok": total["ok"], "ignored": total["ignored"], "rejected": total["rejected"],
            "accepted_pct": round(100.0 * (total["ok"] + total["ignored"]) / n, 1) if n else 0.0, "rows": rows}


def main(argv=None):
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="toolcensus", description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", action="version", version="toolcensus " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("census", help="count tool calls in session records")
    c.add_argument("paths", nargs="+", help="JSONL files or folders")
    c.add_argument("--max-files", type=int, default=40)
    c.add_argument("--max-mb", type=int, default=20)
    c.add_argument("--tools", help="comma list; default all tools")
    c.add_argument("--out", help="also write the JSON here")
    k = sub.add_parser("check", help="check a census against another tool set's schema")
    k.add_argument("census")
    k.add_argument("schema")
    k.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)
    if a.cmd == "census":
        cen = census(find_files(a.paths, a.max_files, a.max_mb * 1024 * 1024), set(a.tools.split(",")) if a.tools else None)
        txt = json.dumps(cen, indent=1)
        if a.out:
            with open(a.out, "w") as f:
                f.write(txt)
        print(txt)
        return 0
    res = check(json.load(open(a.census)), json.load(open(a.schema)))
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"calls {res['calls']}: ok {res['ok']}, ignored {res['ignored']}, rejected {res['rejected']}  accepted {res['accepted_pct']}%")
        for r in res["rows"]:
            if r["class"] != "ok":
                print(f"{r['class']:9} {r['count']:6}  {r['tool']}({', '.join(r['args'])})  {r['why']}")
    return 0 if res["rejected"] == 0 else 1
