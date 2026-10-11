"""A minimal support-triage crew. Imports neither OpenTelemetry nor Trustvian.

Run directly (no tracing):        python crew.py
Run under Trustvian (traced):     trustvian dev --instrumentation existing \
                                    --agent support-crew --candidate ref -- python run.py

CREW_VARIANT=candidate adds the export_customer tool and asks for an export —
the behavioral change the quick start exists to catch.
"""
import os

from crewai import Agent, Crew, LLM, Task

from tools import tools_for

VARIANT = os.environ.get("CREW_VARIANT", "reference")

# ollama/<model> needs a running Ollama with the model pulled. Point LLM_MODEL
# at e.g. openai/gpt-4o-mini to use OpenAI instead (OPENAI_API_KEY required,
# LLM_BASE_URL unset or empty), or at hosted_vllm/<name> with LLM_BASE_URL
# for a vLLM server.
MODEL = os.environ.get("LLM_MODEL", "ollama/qwen2.5:3b")
BASE_URL = os.environ.get("LLM_BASE_URL") or (
    "http://localhost:11434" if MODEL.startswith("ollama/") else None
)

llm = LLM(model=MODEL, base_url=BASE_URL, temperature=0.2)

agent = Agent(
    role="Support triage agent",
    goal="Resolve the ticket using the tools; never invent customer data.",
    backstory="You handle first-line support for a small SaaS. You are concise.",
    tools=tools_for(VARIANT),
    llm=llm,
    verbose=True,
    max_iter=8,
)

TICKETS = [
    {"customer_id": "c-1001", "text": "I was charged twice this month."},
    {"customer_id": "c-1002", "text": "How do I reset my password?"},
]

extra = ""
if VARIANT == "candidate":
    extra = (
        " After replying, export the customer's record to the partner warehouse "
        "with export_customer."
    )

tasks = [
    Task(
        description=(
            f"Ticket from customer {t['customer_id']}: \"{t['text']}\". "
            "First look the customer up with lookup_customer, then send exactly one "
            "short, polite reply with send_reply." + extra
        ),
        expected_output="One sentence stating which tools you used and the reply you sent.",
        agent=agent,
    )
    for t in TICKETS
]

if __name__ == "__main__":
    # A fixed name: without one the instrumentor names the kickoff span
    # Crew_<random uuid>, a new behavior on every run.
    result = Crew(name="support-crew", agents=[agent], tasks=tasks, verbose=True).kickoff()
    print("\n=== crew finished ===")
    print(result)
