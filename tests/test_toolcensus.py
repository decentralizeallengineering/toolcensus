import json

from toolcensus import census, check, classify, find_files, main

SECRET = "hunter2-do-not-leak"


def rec(name, **inp):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": SECRET}, {"type": "tool_use", "name": name, "input": inp}]}})


def write(tmp_path, lines, name="s.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\nnot json\n" + json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
    return str(p)


SCHEMA = {"unknown_args": "reject", "tools": {
    "Read": {"args": {"file_path": "str", "offset": "int"}, "required": ["file_path"], "aliases": {"path": "file_path"}},
    "Bash": {"args": {"command": "str", "timeout": "number"}, "required": ["command"]}}}


def test_census_counts_names_and_types_only(tmp_path):
    f = write(tmp_path, [rec("Read", file_path=SECRET), rec("Read", file_path="b", offset=3), rec("Bash", command="ls", timeout=1.5), rec("Read", file_path="c")])
    cen = census([f])
    assert cen["calls"] == {"Read": 3, "Bash": 1}
    assert cen["args"]["Read"] == {"file_path": 3, "offset": 1}
    top = cen["sets"][0]
    assert top["tool"] == "Read" and top["count"] == 2 and top["args"] == [["file_path", "str"]]
    assert SECRET not in json.dumps(cen)


def test_census_tool_filter_and_find_files_limits(tmp_path):
    write(tmp_path, [rec("Read", file_path="a"), rec("Bash", command="x")], "a.jsonl")
    write(tmp_path, [rec("Read", file_path="a")], "b.jsonl")
    fs = find_files([str(tmp_path)], max_files=1)
    assert len(fs) == 1
    assert census(find_files([str(tmp_path)]), {"Bash"})["calls"] == {"Bash": 1}
    assert find_files([str(tmp_path)], max_bytes=1) == []


def test_classify_ok_alias_type_missing_unknown():
    assert classify({"tool": "Read", "args": [["file_path", "str"], ["offset", "int"]]}, SCHEMA)[0] == "ok"
    assert classify({"tool": "Read", "args": [["path", "str"]]}, SCHEMA)[0] == "ok"
    assert classify({"tool": "Bash", "args": [["command", "str"], ["timeout", "int"]]}, SCHEMA)[0] == "ok"
    c, why = classify({"tool": "Read", "args": [["file_path", "int"]]}, SCHEMA)
    assert c == "rejected" and "wants str" in why
    assert classify({"tool": "Read", "args": [["offset", "int"]]}, SCHEMA) == ("rejected", "missing file_path")
    assert classify({"tool": "Glob", "args": []}, SCHEMA) == ("rejected", "unknown tool")
    assert classify({"tool": "Bash", "args": [["command", "str"], ["bg", "bool"]]}, SCHEMA)[0] == "rejected"
    lax = dict(SCHEMA, unknown_args="ignore")
    assert classify({"tool": "Bash", "args": [["command", "str"], ["bg", "bool"]]}, lax) == ("ignored", "no effect: bg")


def test_check_weights_by_call_count(tmp_path):
    f = write(tmp_path, [rec("Read", file_path="a")] * 3 + [rec("Glob", pattern="*")])
    res = check(census([f]), SCHEMA)
    assert (res["calls"], res["ok"], res["rejected"], res["accepted_pct"]) == (4, 3, 1, 75.0)


def test_cli_census_then_check(tmp_path, capsys):
    f = write(tmp_path, [rec("Read", file_path="a"), rec("Bash", command="ls", background=True)])
    out, sch = tmp_path / "c.json", tmp_path / "schema.json"
    sch.write_text(json.dumps(SCHEMA))
    assert main(["census", f, "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["check", str(out), str(sch)]) == 1  # one rejected shape: nonzero exit
    text = capsys.readouterr().out
    assert "accepted 50.0%" in text and "unknown argument background" in text


def test_check_takes_mcp_anthropic_and_openai_tool_lists(tmp_path):
    js = {"type": "object", "properties": {"file_path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["file_path"]}
    strict = dict(js, additionalProperties=False)
    f = write(tmp_path, [rec("Read", file_path="a"), rec("Read", file_path="a", limit="9"), rec("Read", file_path="a", extra=1), rec("Glob")])
    cen = census([f])
    docs = [
        {"tools": [{"name": "Read", "inputSchema": js}]},                                  # MCP tools/list result
        {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "Read", "inputSchema": js}]}},  # whole JSON-RPC reply
        [{"name": "Read", "input_schema": js}],                                            # Anthropic tools
        [{"type": "function", "function": {"name": "Read", "parameters": js}}],           # OpenAI tools
    ]
    for doc in docs:
        res = check(cen, doc)
        assert (res["ok"], res["ignored"], res["rejected"]) == (1, 1, 2), doc  # str limit and unknown Glob rejected
    res = check(cen, {"tools": [{"name": "Read", "inputSchema": strict}]})
    assert (res["ok"], res["ignored"], res["rejected"]) == (1, 0, 3)  # additionalProperties false rejects extra
