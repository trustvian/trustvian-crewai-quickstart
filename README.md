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

## 6. What you learned, what is still missing

- Run the agent twice and the second run's anomaly confidence goes up: the
  engine keeps a file baseline per candidate (`~/.trustvian/dev/<hash>/`).
- `trustvian eval run --scenario` (N runs from a scenario file) and the PR
  comment do not exist yet (tasks 078/079). For now, compare two run ids.
- If the model fails to call tools (it happens with 4B models) the behavior
  set comes out incomplete; that is a model finding, not a Trustvian finding.
  Try a larger model via `LLM_MODEL`.

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
