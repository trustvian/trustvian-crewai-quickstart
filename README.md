# Trustvian + CrewAI — Quick Start (step by step)

Goal: run a small CrewAI agent under `trustvian dev` **without changing the
agent's code**, watch the live behavior graph, then give the agent a new tool
and watch Trustvian report the behavioral change and fail the gate.

Time: about 15 minutes for the first run (model download excluded).

## 0. Prerequisites

| What | How |
|---|---|
| Ollama + a model | `ollama pull gemma3:4b` (3.3 GB). To use OpenAI instead, see the `LLM_MODEL` note at the end. |
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
process, turns on the CrewAI + LiteLLM + requests instrumentors, and then
runs `crew.py` as-is.

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
llm  · gemma3:4b
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

Expected: `+ tool · export_customer` added, `Gate: FAIL`, exit code 1. Run the
same command with `--max-added-behaviors 1` and it passes. The Compare tab in
the WebUI shows the same result; clicking a finding jumps to the observations
that are its evidence.

## 6. What you learned, what is still missing

- Run the agent twice and the second run's anomaly confidence goes up: the
  engine keeps a file baseline per candidate (`~/.trustvian/dev/<hash>/`).
- `trustvian eval run --scenario` (N runs from a scenario file) and the PR
  comment do not exist yet (tasks 078/079). For now, compare two run ids.
- If the model fails to call tools (it happens with 4B models) the behavior
  set comes out incomplete; that is a model finding, not a Trustvian finding.
  Try a larger model via `LLM_MODEL`.

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
