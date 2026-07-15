# Skill: control Fleetex from the CLI

Fleetex (a self-hosted LaTeX editor) is **agent-native**: the whole application
can be driven from the command line via `fleetex app <command>`, no browser
needed. Every command accepts `--json` for machine-readable output.

## Setup (once)

The stack must be running (`fleetex up`). Then authenticate — the session is
cached in `~/.fleetex/session.json` and reused automatically:

```bash
fleetex app register --email you@example.com --password 'secret123'   # or `login`
```

## Commands

| Command | What it does |
| --- | --- |
| `fleetex app login \| register \| logout \| whoami` | session management |
| `fleetex app projects` | list your projects (`id  access  name`) |
| `fleetex app new "<name>"` | create a project → prints its id |
| `fleetex app rm <id>` / `rename <id> "<name>"` | delete / rename |
| `fleetex app tree <id>` | list files (`type  /path`) |
| `fleetex app mkdir <id> "<name>" [--folder PATH]` | create a folder |
| `fleetex app mkdoc <id> "<name>" [--folder PATH]` | create a document |
| `fleetex app upload <id> <file> [--folder PATH] [--name N]` | upload a file (into a folder) |
| `fleetex app pull <id> <path> [-o file]` | print/save a document's text |
| `fleetex app push <id> <path> [-f file]` | set a document's text (or stdin) |
| `fleetex app compile <id> [-o out.pdf]` | compile and save the PDF |
| `fleetex app download <id> [-o out.zip]` | download the project zip (+ compiled PDF) |
| `fleetex app members <id> [--add EMAIL --level readAndWrite \| --remove USER_ID]` | sharing |

Add `--json` to any command for structured output. Exit code is non-zero on
failure (e.g. a failed compile), so commands are scriptable.

## Agent recipe: write a doc and compile it

```bash
fleetex app login --email you@example.com --password 'secret123'
PID=$(fleetex app new "Paper" --json | jq -r .project_id)
cat paper.tex | fleetex app push "$PID" main.tex
fleetex app compile "$PID" -o paper.pdf --json      # {"status":"success","pdf":"paper.pdf",...}
fleetex app download "$PID" -o paper.zip            # sources + compiled PDF
```

## Interactive REPL

For a stateful session (pick a project once, then run many commands), use the
shell. It reuses one login and a selected project, so `<project>` can be omitted:

```
$ fleetex app repl
fleetex[-]> use 6a57...e7b
fleetex[03e7b]> mkdir chapters
fleetex[03e7b]> mkdoc intro.tex --folder chapters
fleetex[03e7b]> compile
fleetex[03e7b]> exit
```

It reads from stdin, so you can also pipe a script:
`printf 'use PID\ncompile\nexit\n' | fleetex app repl`.

## Discovery

- `fleetex --help` and `fleetex app --help` list every command and flag.
- `fleetex doctor` verifies prerequisites (Docker, Compose, disk).
- All mutating commands are idempotent-friendly and report a clear error (with a
  `login` hint) when unauthenticated.
