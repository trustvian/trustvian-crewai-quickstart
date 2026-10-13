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
| Trustvian v0.12.0 | **(a)** release archive: download the v0.12.0 macOS/Linux archive from the [release page](https://github.com/trustvian/trustvian/releases/tag/v0.12.0), extract it, add the directory to `PATH` — `trustvian`, `trustvian-local` and `trustvian-collector` ship side by side. **(b)** from a checkout: `git clone --branch v0.12.0 https://github.com/trustvian/trustvian && cd trustvian && make build dev-binaries && export PATH="$PWD/bin:$PATH"` |
| Check | `trustvian version` prints `v0.12.0`; `trustvian dev --help` must work. |

`dev` does not run on Windows; use WSL2.

## 1. Project files

The files in this folder:

```text
requirements.txt     CrewAI + OpenInference + OTel SDK
mock_services.py     fake CRM on 127.0.0.1:8081 (standard library, no dependencies)
tools.py             the agent's tools — imports NEITHER OTel NOR Trustvian
crew.py              the agent and its tasks — imports NEITHER OTel NOR Trustvian
run.py               instrumentation harness; runs crew.py unchanged
live.py              live mode (step 7): one trustvian dev per agent, supervised
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
each its own process, its own actor and its own Trustvian run, work a ticket
every few seconds until you stop them, so the live view fills continuously.

| Agent (`service.name`) | Tools | Tickets (eight each, e.g.) |
|---|---|---|
| `support-agent` | `lookup_customer`, `send_reply` | "How do I reset my password?" |
| `billing-agent` | `lookup_customer`, `lookup_invoice`, `issue_refund` | "I was charged twice this month." |
| `accounts-agent` | `lookup_customer`, `change_plan` | "Please upgrade me to Pro." |

`live.py` starts one `trustvian dev` per role, all attached to one control
plane that is already running:

```text
trustvian dev --api-url $TRUSTVIAN_API_URL --project trustvian-crewai-quickstart \
  --agent <role>-agent --candidate live-<role> --instrumentation existing \
  -- python run.py
```

with `LIVE_ROLE=<role>` in its environment; `crew.py` sees `LIVE_ROLE` and
works each of that role's tickets with a one-agent crew. dev exports
`--agent` as `OTEL_SERVICE_NAME` and starts a Collector of its own, and each
role learns into a baseline of its own (the candidate is dev's learning
scope). Two things happen on purpose, and rarely:

- **Drift.** Every 20th billing ticket also binds `export_customer` and asks
  for an export: a new behavior on an agent Trustvian has already learned.
- **Failed calls.** The fake CRM answers about 5% of requests with `503`
  (`429` for refunds). The tool returns a short failure to the model, which
  usually tries again.

Three terminals. **Terminal A**, the CRM from step 2. **Terminal C**, the
control plane every run attaches to, on a state directory of its own (the
standalone command from Trustvian's `docs/local-development.md`, "Running the
parts separately"):

```bash
trustvian-local --state-dir ~/.trustvian/live --listen 127.0.0.1:8080
```

It prints `Web: http://127.0.0.1:8080/`; open it. **Terminal B**, with step
3's exports:

```bash
export TRUSTVIAN_API_URL=http://127.0.0.1:8080
python live.py
```

Without `TRUSTVIAN_API_URL`, `live.py` exits with one line naming the
`trustvian-local` command above. It prints each run id as its dev reports it,
then one line per ticket, never its text:

```text
live: 3 agents (support-agent, billing-agent, accounts-agent), one run each on http://127.0.0.1:8080, one ticket each every ~10 s, until stopped (Ctrl-C)
live: watch at http://127.0.0.1:8080/
support-agent   run dev-live-support-20261012T102217.146Z
billing-agent   run dev-live-billing-20261012T102217.281Z
accounts-agent  run dev-live-accounts-20261012T102217.357Z
support-agent   ticket 1    tools: lookup_customer, send_reply  (2.7 s)  failed calls: 1
billing-agent   ticket 20   tools: issue_refund, lookup_customer, export_customer, lookup_invoice  (4.0 s)  failed calls: 1  [drift]
accounts-agent  ticket 11   tools: lookup_customer, change_plan  (1.9 s)  failed calls: 1
```

Stop it with **Ctrl-C** in Terminal B: `live.py` sends every dev `SIGINT`,
each stops its agent and completes its run (`… run dev-live-… complete`),
and `live.py` prints the tickets per agent and exits 0. A dev still running
after 20 s (`LIVE_STOP_GRACE_SECONDS`) is killed, its Collector and agent
with it. A dev that exits early is restarted after a back-off, as a new run
with a new card; the others keep working. Stop Terminal C afterwards; its
state keeps the runs.

**What you will see** in the WebUI's Live page:

- **Three cards under "Active now"**, `support-agent`, `billing-agent` and
  `accounts-agent`, each with its run id, the most recently active first.
- **The newest activity is followed**: the canvas and the Inspector switch
  to whichever agent sent the latest observations ("Following newest
  activity").
- **Click a card to follow that agent.** The view stays on it ("Pinned to
  your selection") while the other cards keep counting.
- **Follow active** goes back to following the newest activity.

What a 6-minute run showed (Trustvian v0.10.0, `qwen2.5:3b` on an Apple M3
Pro laptop, Ollama with `OLLAMA_NUM_PARALLEL=1`):

- **Three cards, one per agent**, and three runs, each `completed` after
  Ctrl-C, which took 2 s; no dev, Collector or agent was left running.
- **A steady stream.** 83 tickets (28, 27 and 28), about 730 observations;
  a ticket took 1.8–2.9 s at the median and 6.4 s at most.
- **Each agent's behaviors, in its own run:** `external/qwen2.5:3b → openai`
  (CrewAI reaches Ollama through the OpenAI client), `http/GET` and
  `http/POST → 127.0.0.1`, the crew's `rpc/<role>-crew.kickoff` and
  `rpc/<Role> agent._execute_core`, and the agent's tools: 7 for
  `support-agent` and `accounts-agent`, 9 for `billing-agent` (its three
  tools and the drift's `export_customer`).
- **The drift** appeared once, at billing ticket 20, about 4¼ minutes in, on
  the `billing-agent` card; the Inspector opened `tool export_customer`,
  NEW, once the view followed it.
- **Failed calls:** 15, each the `503` or `429` of one CRM request (8 for
  `support-agent`, 5 for `billing-agent`, 2 for `accounts-agent`); the runs
  went on.

What the live view does not do at Trustvian v0.10.0:

- **No pause.** The view keeps moving; to hold one agent still, pin its card.
- **The canvas draws from the moment you select a run.** The stream keeps
  no history, so a pinned card's canvas fills as new observations arrive; a
  one-off such as the drift is drawn only if it arrives while that run is
  shown. The Live stream table below lists every agent's rows, whichever card
  is pinned. Earlier evidence is under Runs.

The knobs, all environment variables:

| Variable | Default | |
|---|---|---|
| `TRUSTVIAN_API_URL` | none; required | the control plane every dev attaches to |
| `LIVE_AGENTS` | `support,billing,accounts` | the roles to run, one dev each |
| `LIVE_INTERVAL_SECONDS` | `10` | one ticket per agent this often, ±50% jitter |
| `LIVE_DRIFT_EVERY` | `20` | every Nth billing ticket also exports; `0` = never |
| `LIVE_MAX_TICKETS` | `0` | tickets per agent, then that run completes; `0` = until stopped |
| `LIVE_STOP_GRACE_SECONDS` | `20` | how long Ctrl-C waits for the runs to complete |
| `CRM_ERROR_RATE` | `0.05` | share of CRM requests that fail; `0` = none. Read by `mock_services.py`, so set it in Terminal A |

The three agents share one model server. Ollama serves
`OLLAMA_NUM_PARALLEL` requests at a time and queues the rest; at `1`, as
measured above, a ticket waits for the other agents' model calls, which is
what the median includes. A slower model needs a longer
`LIVE_INTERVAL_SECONDS`. Each role learns into its own baseline under
`~/.trustvian/dev/`, kept between sessions, so the next session is scored
against what this one taught.

With Docker Compose, live mode is a service of its own: `python live.py` in
one container, its three dev processes and three Collectors attached to the
stack's control plane with `TRUSTVIAN_API_URL=http://control-plane:8080`:

```bash
docker compose --profile live up -d       # builds its image the first time
# open http://127.0.0.1:8080/
docker compose logs -f live               # the run ids and the per-ticket lines
docker compose --profile live down        # stops it; every dev completes its run
```

`down` keeps the volumes, so the next `up` is scored against what this one
taught; `down -v` forgets it. The knobs go in `.env`. The `agent` service
and its subcommands are unchanged.

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

The first build clones Trustvian (`TRUSTVIAN_REF`, default `v0.12.0`) and
compiles `trustvian` and `trustvian-local`; `trustvian-collector` is copied
out of the signed release image
`ghcr.io/trustvian/trustvian-collector:v0.12.0`, pinned by digest
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
