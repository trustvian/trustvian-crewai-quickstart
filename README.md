# Trustvian + CrewAI — Quick Start (step by step)

Goal: run a small CrewAI agent under `trustvian dev` **without changing the
agent's code**, watch the live behavior graph, then give the agent a new tool
and watch Trustvian report the behavioral change and fail the gate.

Time: about 15 minutes for the first run (model download excluded).

## 0. Prerequisites

| What | How |
|---|---|
| Ollama + a model | `ollama pull qwen2.5:3b` (1.9 GB). The model must support tool calling (`ollama show <model>` lists `tools`); gemma3 does not. To use OpenAI instead, see the `LLM_MODEL` note at the end. |
| Python 3.11+ | `python3 --version` |
| Trustvian binaries | **(a)** release archive: download the macOS/Linux archive, extract it, add the directory to `PATH` — `trustvian`, `trustvian-local` and `trustvian-collector` ship side by side. **(b)** from a checkout: `git clone https://github.com/trustvian/trustvian && cd trustvian && make build dev-binaries && export PATH="$PWD/bin:$PATH"` |
| Check | `trustvian dev --help` must work. |

`dev` does not run on Windows; use WSL2.

## 1. Project files

The files in this folder:

```text
requirements.txt     CrewAI + OpenInference + OTel SDK
mock_services.py     fake CRM on 127.0.0.1:8081 (standard library, no dependencies)
tools.py             the agent's tools — imports NEITHER OTel NOR Trustvian
crew.py              the agent and its tasks — imports NEITHER OTel NOR Trustvian
run.py               instrumentation harness; runs crew.py unchanged
live.py              live mode (step 7): starts and supervises three agents
roles.py             live mode's roles, tickets and per-worker loop
tests/               live mode and content checks; no model needed
```

`crew.py` and `tools.py` are your application; neither knows OpenTelemetry
exists. `run.py` stands in for a framework's own instrumentation: it builds
the SDK from the environment variables `trustvian dev` hands the child
process, turns on the CrewAI + OpenAI + requests instrumentors (and LiteLLM's
when it is installed), and then runs `crew.py` as-is.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Start the fake CRM (Terminal A)

```bash
python mock_services.py
# listening on http://127.0.0.1:8081
```

## 3. Reference run (Terminal B)

```bash
export CREWAI_DISABLE_TELEMETRY=true      # CrewAI's own anonymous telemetry; do NOT use OTEL_SDK_DISABLED
export OPENINFERENCE_HIDE_INPUTS=true     # keep prompt/output content out of spans
export OPENINFERENCE_HIDE_OUTPUTS=true

trustvian dev --instrumentation existing \
  --agent support-crew --candidate ref \
  -- python run.py
```

The banner shows `Run dev-ref-...` (note the run id) and `Web http://127.0.0.1:<port>/`.
Open the web address: in the live view, under the `support-crew` actor, you
should see

```text
tool · lookup_customer      (GET → 127.0.0.1:8081 beneath it)
tool · send_reply           (POST → 127.0.0.1:8081 beneath it)
llm  · qwen2.5:3b
```

All of them are NEW on the first run. When the agent finishes, dev prints
"Run ... complete".

## 4. Candidate run: add a tool to the agent

`CREW_VARIANT=candidate` enables a third tool (`export_customer`) and the task
text nudges the agent to use it. No code change, only an environment variable;
in real life this would be a pull request.

```bash
CREW_VARIANT=candidate \
trustvian dev --instrumentation existing \
  --agent support-crew --candidate cand \
  -- python run.py
```

Note the run id (`dev-cand-...`).

## 5. Compare

```bash
trustvian eval compare \
  --reference-run dev-ref-<...> --candidate-run dev-cand-<...> \
  --max-added-behaviors 0 --max-block-decisions 0 --max-critical-risk-observations 0
echo "exit: $?"
```

Expected: `Behaviors: +1 / …`, `FAIL Added behaviors: 1 (maximum 0)`,
`Gate: FAIL`, exit code 1. The added behavior is the `export_customer` tool;
`--json` lists it under `behavior_diff`. Run the same command with
`--max-added-behaviors 1` and it passes. The Compare tab in the WebUI shows
the same result; clicking a finding jumps to the observations that are its
evidence.

## 6. What you learned, and where to go next

- Run the agent twice and the second run's anomaly confidence goes up: the
  engine keeps a file baseline per candidate (`~/.trustvian/dev/<hash>/`).
- One run is a sample. Repeating the comparison N times per side from a
  scenario file (`trustvian eval run --scenario`) and posting the result as a
  pull request comment (the GitHub Action) both ship in v0.10.0: see
  [`docs/platform-cli.md`](https://github.com/trustvian/trustvian/blob/v0.10.0/docs/platform-cli.md)
  and
  [`docs/ci-github-action.md`](https://github.com/trustvian/trustvian/blob/v0.10.0/docs/ci-github-action.md).
- If the model fails to call tools (it happens with 4B models) the behavior
  set comes out incomplete; that is a model finding, not a Trustvian finding.
  Try a larger model via `LLM_MODEL`.

## 7. Live mode: a fleet that keeps working

Steps 3–5 are runs that end. Live mode is one that does not: three agents,
each its own process and its own actor, work a ticket every few seconds until
you stop them, so the live view fills continuously.

| Actor (`service.name`) | Tools | Tickets (eight each, e.g.) |
|---|---|---|
| `support-agent` | `lookup_customer`, `send_reply` | "How do I reset my password?" |
| `billing-agent` | `lookup_customer`, `lookup_invoice`, `issue_refund` | "I was charged twice this month." |
| `accounts-agent` | `lookup_customer`, `change_plan` | "Please upgrade me to Pro." |

`live.py` starts one worker per role, each `python run.py` with
`OTEL_SERVICE_NAME=<role>-agent` and `LIVE_ROLE=<role>`; `crew.py` sees
`LIVE_ROLE` and works each of that role's tickets with a one-agent crew. Two things
happen on purpose, and rarely:

- **Drift.** Every 20th billing ticket also binds `export_customer` and asks
  for an export: a new behavior on an actor Trustvian has already learned.
- **Failed calls.** The fake CRM answers about 5% of requests with `503`
  (`429` for refunds). The tool returns a short failure to the model, which
  usually tries again.

With the CRM from step 2 running (Terminal A) and step 3's exports:

```bash
trustvian dev --instrumentation existing \
  --agent support-fleet --candidate live \
  -- python live.py
```

`live.py` prints one line per ticket, never its text:

```text
live: 3 agents (support-agent, billing-agent, accounts-agent), one ticket each every ~10 s, until stopped (Ctrl-C)
support-agent   ticket 1    tools: send_reply, lookup_customer  (2.5 s)
billing-agent   ticket 20   tools: lookup_customer, lookup_invoice, export_customer, issue_refund  (4.1 s)  [drift]
billing-agent   ticket 3    tools: lookup_invoice, issue_refund, lookup_customer  (3.5 s)  failed calls: 1
```

Stop it with **Ctrl-C**: `live.py` stops every worker (SIGTERM, SIGKILL after
5 s), prints the tickets per agent and exits 0, and dev prints `Run
dev-live-… complete.`

What a 5½-minute run showed (Trustvian v0.10.0, `qwen2.5:3b` on an Apple M3
Pro laptop, Ollama with `OLLAMA_NUM_PARALLEL=1`):

- **One agent in the live view, three actors in the evidence.** The live
  view's Agent, its Behavior flow and every Live stream row name the run's
  agent, `support-fleet`. Which worker did what is in each observation's
  `actor_id` (`support-agent`, `billing-agent`, `accounts-agent`), which
  `GET /v1/evaluation-runs/<run>/observations` returns. The roles also show
  in the behavior names, because CrewAI names its spans after the crew and the
  agent: `rpc/billing-crew.kickoff`, `rpc/Billing agent._execute_core`.
- **A steady stream.** 80 tickets (27, 26 and 27), about 700 observations;
  a ticket took 2–3 s at the median and 6 s at most, so the 10 s interval
  keeps up even with the three workers queueing on one model.
- **15 behaviors.** `external/qwen2.5:3b → openai` (CrewAI reaches Ollama
  through the OpenAI client), `http/GET` and `http/POST → 127.0.0.1`, a
  `rpc/<role>-crew.kickoff` and a `rpc/<Role> agent._execute_core` per role,
  and six tools, each under the actor whose role has it: `lookup_customer`,
  `send_reply`, `lookup_invoice`, `issue_refund`, `change_plan`, and the
  drift's `export_customer`.
- **The drift** appeared once, at billing ticket 20, about four minutes in:
  `tool/export_customer`, NEW.
- **Failed calls:** 10 HTTP observations with an error status, each the
  `503` or `429` of one CRM request; the run went on.

The knobs, all environment variables:

| Variable | Default | |
|---|---|---|
| `LIVE_AGENTS` | `support,billing,accounts` | the roles to run |
| `LIVE_INTERVAL_SECONDS` | `10` | one ticket per agent this often, ±50% jitter |
| `LIVE_DRIFT_EVERY` | `20` | every Nth billing ticket also exports; `0` = never |
| `LIVE_MAX_TICKETS` | `0` | tickets per agent, then stop; `0` = until stopped |
| `CRM_ERROR_RATE` | `0.05` | share of CRM requests that fail; `0` = none. Read by `mock_services.py`, so set it in Terminal A |

The three workers share one model server. Ollama serves
`OLLAMA_NUM_PARALLEL` requests at a time and queues the rest; at `1`, as
measured above, a ticket waits for the other agents' model calls, which is
what the median includes. A slower model needs a longer
`LIVE_INTERVAL_SECONDS`.

With Docker Compose, live mode is a service of its own, attached to the
stack's control plane:

```bash
docker compose --profile live up -d       # builds its image the first time
# open http://127.0.0.1:8080/
docker compose logs -f live               # the per-ticket lines
docker compose --profile live down        # stops it; dev completes the run
```

`down` keeps the volumes, so the next `up` is scored against what this one
taught; `down -v` forgets it. The knobs go in `.env`; `TRUSTVIAN_LIVE_AGENT`
renames `support-fleet`. The `agent` service and its subcommands are
unchanged.

CrewAI's instrumentor copies each task's description — here, the ticket
text — onto its kickoff span as `crew_tasks`, and no `OPENINFERENCE_HIDE_*`
option covers it. `run.py` drops that attribute, and the few like it, before
anything is exported (steps 3–5 included). The tests prove no ticket text
reaches a span, and cover `live.py`; they need no model:

```bash
pip install -r requirements-dev.txt
pytest
```

## Running it with Docker Compose

The same five steps with nothing installed on the laptop but Docker and a
model server. Trustvian is built from source inside the image, so no release
archive or Go toolchain is needed either.

| Service | What it is |
|---|---|
| `control-plane` | `trustvian-local` with its SQLite database in a named volume; WebUI and API on `http://127.0.0.1:8080/` |
| `crm` | `mock_services.py` |
| `agent` | one-shot container: `trustvian dev --api-url http://control-plane:8080 … -- python run.py`. Used with `docker compose run`, never started by `up` |
| `ollama` | the model server, CPU inference, models in the `ollama-models` volume |
| `ollama-pull` | one-shot: pulls `LLM_MODEL` into `ollama` on `up`, then exits. The agent waits for it to finish |

Why one long-lived control plane instead of letting `dev` start its own: `dev`
starts a private runtime per invocation and stops it when the run ends. Two
runs that need comparing must share one database, and the browser needs the
server to outlive the run that produced it — so the stack runs one control
plane and every run attaches with `--api-url`, the shape Trustvian's
`docs/local-development.md` calls "running the parts separately" and the one CI
uses.

Files: `compose.yaml`, `Dockerfile` (Trustvian build, release collector image,
control plane, agent runner), `compose/control-plane.sh`, `compose/agent-entrypoint.sh`,
`.env.example`.

### 1. Build and start

```bash
cp .env.example .env              # optional; every value has a default
docker compose --profile agent build  # the control-plane and agent images
docker compose up -d
```

`--profile agent` matters: the agent is not started by `up`, so a plain
`docker compose up --build` never rebuilds it and a changed
`requirements.txt` would not reach the image.

The first build clones Trustvian (`TRUSTVIAN_REF`, default `v0.10.0`) and
compiles `trustvian` and `trustvian-local`; `trustvian-collector` is copied
out of the signed release image
`ghcr.io/trustvian/trustvian-collector:v0.10.0`, pinned by digest
(`TRUSTVIAN_COLLECTOR_IMAGE`). Then it installs CrewAI — a few minutes. To
move to another release, change both values in `.env` together. The first `up` also pulls the model
(`qwen2.5:3b`, 1.9 GB) into the `ollama` service; `docker compose logs -f
ollama-pull` shows when it is ready. Afterwards `http://127.0.0.1:8080/` is
the WebUI, published on the host's loopback only (the runtime is
unauthenticated).

### 2. The model

- **Ollama inside Compose (default).** Nothing to do: `ollama-pull` pulled
  `LLM_MODEL` on `up`. To change the model, set `LLM_MODEL=ollama/<model>` in
  `.env` and run `docker compose up -d` again. It must support tool calling:
  `docker compose exec ollama ollama show <model>` lists `tools`. gemma3
  does not — Ollama answers `400 does not support tools` and CrewAI falls
  back to slower, text-parsed tool calls.
- **Ollama on the host.** Faster on a Mac (Metal; Docker is CPU-only there).
  Set `LLM_BASE_URL=http://host.docker.internal:11434` in `.env`, keep the
  Ollama app running and `ollama pull` the model on the host; `ollama-pull`
  then skips. On Linux, Ollama must listen on all interfaces:
  `OLLAMA_HOST=0.0.0.0 ollama serve`.
- **vLLM or OpenAI.** See `.env.example`; the same `LLM_MODEL` / `LLM_BASE_URL`
  pair as in the native flow.

A 3B model on CPU takes about a minute per run and often repeats its tool
calls until `max_iter`; the behavior set is still right. `qwen2.5:7b` follows
the prompt better if Docker has the memory for it.

### 3–5. Reference, candidate, compare

```bash
docker compose run --rm agent reference    # prints "run id ref-<timestamp>"
docker compose run --rm agent candidate    # prints "run id cand-<timestamp>"
docker compose run --rm agent compare      # gates the last two; exit 1 = FAIL
echo "exit: $?"
```

`compare` takes two explicit ids too: `docker compose run --rm agent compare
ref-… cand-…`. The gate limits come from `MAX_ADDED_BEHAVIORS`,
`MAX_BLOCK_DECISIONS`, `MAX_CRITICAL_RISK_OBSERVATIONS` (all default 0), passed
with `-e`: `docker compose run --rm -e MAX_ADDED_BEHAVIORS=1 agent compare`.
Expected result is the same as in the native flow: `Behaviors: +1 / …`,
`FAIL Added behaviors: 1 (maximum 0)`, `Gate: FAIL`, exit 1, with
`export_customer` as the added behavior; the Compare tab in the WebUI shows it.

Two things read differently from the native flow:

- `dev`'s banner prints `Web http://control-plane:8080/` — that is the name
  inside the Compose network. On the host, open `http://127.0.0.1:8080/`.
- Run ids are `ref-<utc time>` / `cand-<utc time>`, chosen by the entrypoint
  so `compare` can find the last pair without parsing `dev`'s output.

### Other commands

```bash
docker compose run --rm agent trustvian eval get --id ref-…   # any CLI command, --api-url pre-set
docker compose run --rm agent shell                           # bash in the agent container
docker compose run --rm agent python crew.py                  # the crew without tracing
docker compose logs control-plane                             # the runtime's log
docker compose down                                           # stop; runs and baselines are kept
docker compose down -v                                        # stop and discard all state
```

Editing `crew.py` or `tools.py` needs no rebuild (the directory is
bind-mounted); changing `requirements.txt` does: `docker compose build agent`
(naming the service enables its profile).

### Compose troubleshooting

| Symptom | Cause / fix |
|---|---|
| `the control plane did not answer at http://control-plane:8080` | `docker compose ps` — is `control-plane` healthy? `docker compose logs control-plane` has the reason |
| `ConnectionError: Failed to connect to OpenAI API` | The model server is not reachable from the agent. Default stack: `docker compose ps ollama` and `docker compose logs ollama-pull`. Host Ollama: is the app running? On Linux, `OLLAMA_HOST=0.0.0.0` |
| `does not support tools` / red "LLM Error" panels | The model has no tool calling (gemma3). Pick one whose `ollama show` lists `tools` |
| WebUI shows the project but no behaviors | The run failed before the first model answer — `docker compose run --rm agent trustvian eval get --id <run id>` shows `failed`; fix the model, run again |
| Build fails while fetching Go modules or cloning | Network/proxy on the build host; `TRUSTVIAN_REF` must be a branch, tag or full SHA that exists |
| Build fails pulling `ghcr.io/trustvian/trustvian-collector` | Registry unreachable, or `TRUSTVIAN_COLLECTOR_IMAGE` names a digest that does not exist; `docker pull` it by hand to see the error |
| `compare` says no run recorded | Run `reference` and `candidate` first, or pass the two ids explicitly |
| Everything reports NEW on every run | You ran `docker compose down -v` in between; the volumes hold the baseline and the runs |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| dev says "cannot establish instrumentation ownership" | `--instrumentation existing` is missing |
| dev says "cannot determine which agent" | `--agent support-crew` is missing, or `OTEL_SERVICE_NAME` is unset |
| Live view is empty | Does `run.py` print "exporter → http://127.0.0.1:.../v1/traces" at startup? If not, `opentelemetry-exporter-otlp-proto-http` is not installed in the venv |
| No `tool ·` rows, only HTTP | `openinference-instrumentation-crewai` is not installed or too old; check with `pip show` |
| No `llm ·` row | LiteLLM instrumentor not installed; if you call the OpenAI SDK directly, add `openinference-instrumentation-openai` and enable it in `run.py` |
| dev stops because of `OTEL_SDK_DISABLED=true` | Use `CREWAI_DISABLE_TELEMETRY=true` to silence CrewAI's telemetry, not that variable |
| Tool calls show up but all go to one host | Expected: 075 reads the tool name, so the behavior is `tool · <name>`; the HTTP child is not counted separately (#132) |

## Using OpenAI instead of Ollama

```bash
export OPENAI_API_KEY=...
export LLM_MODEL=openai/gpt-4o-mini
pip install openinference-instrumentation-openai   # run.py enables it automatically
```
