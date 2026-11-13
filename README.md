# toolcensus

You built a tool set for coding agents. Would it accept the calls a real agent makes?
toolcensus counts the tool calls in your Claude Code session records (tool names,
argument names, value types, never the values), then checks that census against a
schema of your tool set and tells you how many calls it would take as they are.

```
pip install git+https://github.com/decentralizeallengineering/toolcensus
```

## 30-second tour

```
$ toolcensus census ~/.claude/projects --out census.json     # keeps no argument value
$ toolcensus check census.json examples/schema.json
calls 5: ok 2, ignored 2, rejected 1  accepted 80.0%
ignored        1  Bash(command, description)  no effect: description
ignored        1  Edit(file_path, new_string, old_string, replace_all)  no effect: replace_all
rejected       1  Grep(output_mode, pattern)  unknown tool
```

The sample in `examples/` has five calls. Exit code is 1 when anything is rejected, so
it can gate a build.

## Census

`toolcensus census PATH... [--max-files 40] [--max-mb 20] [--tools Read,Bash] [--out FILE]`

Reads the newest `*.jsonl` files under each path (files over `--max-mb` are skipped) and
prints JSON: calls per tool, how often each argument is used, and each distinct
shape, that is a tool plus its argument names and types, with a count. Records are
`assistant` messages holding `tool_use` blocks. Nothing else is read out of them.

## Check

`toolcensus check CENSUS SCHEMA [--json]`

Each recorded shape is classed as
- `ok`: the tool takes it as it is,
- `ignored`: the tool takes it, but an argument is one it does not list (only when the
  schema says `"unknown_args": "ignore"`),
- `rejected`: unknown tool, missing required argument, wrong value type, or an extra
  argument when `unknown_args` is `reject` (the default).

The percentage is by call count, not by shape count. The schema format:

```json
{"unknown_args": "reject",
 "tools": {"Read": {"args": {"file_path": "str", "offset": "int"},
                    "required": ["file_path"],
                    "aliases": {"path": "file_path"}}}}
```

Types are `str int float number bool list dict null any`. `aliases` names an
argument the tool accepts under another name. Python: `from toolcensus import census, check`.

SCHEMA can also be a tool list as another harness exposes it: an MCP `tools/list`
result (or the whole JSON-RPC reply), an Anthropic `tools` list (`input_schema`) or an
OpenAI `tools` list (`function.parameters`). JSON Schema types map to the types above;
an extra argument is `ignored` unless the tool sets `"additionalProperties": false`.

```
$ toolcensus check census.json examples/mcp-tools.json
calls 5: ok 2, ignored 1, rejected 2  accepted 60.0%
ignored        1  Bash(command, description)  no effect: description
rejected       1  Edit(file_path, new_string, old_string, replace_all)  unknown tool
rejected       1  Grep(output_mode, pattern)  unknown tool
```

## Tests

```
pip install -e ".[test]" && pytest
```

Licence: Apache-2.0.

## Related

- [taskmine](https://github.com/decentralizeallengineering/taskmine): turn a repo's history into agent tasks with a proven red-green check
- [codeindex](https://github.com/decentralizeallengineering/codeindex): local code index with an MCP server, a tool set to check against
- [all tools](https://github.com/decentralizeallengineering): the index of this account
