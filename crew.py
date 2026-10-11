"""A minimal support-triage crew. Imports neither OpenTelemetry nor Trustvian.

Run directly (no tracing):        python crew.py
Run under Trustvian (traced):     trustvian dev --instrumentation existing \
                                    --agent support-crew --candidate ref -- python run.py

CREW_VARIANT=candidate adds the export_customer tool and asks for an export —
the behavioral change the quick start exists to catch.

With LIVE_ROLE set (live.py sets it), the crew works that role's tickets
instead, one every few seconds until stopped; see roles.py.
"""
import os

from crewai import Agent, Crew, LLM, Task

import roles
from tools import CALLS, tools_for, tools_named

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


def live_handler(model=None):
    """Live mode's handle(ticket): a one-agent crew with the ticket's tools."""
    def handle(ticket: dict) -> None:
        live_agent = Agent(
            role=f"{ticket['role'].capitalize()} agent",
            goal="Resolve the ticket using the tools; never invent customer data.",
            backstory=ticket["system"],
            tools=tools_named(ticket["tools"]),
            llm=model or llm,
            verbose=False,
            max_iter=8,
        )
        task = Task(
            description=ticket["task"],
            expected_output="One sentence stating which tools you used.",
            agent=live_agent,
        )
        # A fixed name per role, for the same reason as support-crew below.
        Crew(name=f"{ticket['role']}-crew", agents=[live_agent], tasks=[task]).kickoff()

    return handle


if __name__ == "__main__":
    if os.environ.get("LIVE_ROLE"):
        roles.serve(live_handler(), CALLS)
    else:
        # A fixed name: without one the instrumentor names the kickoff span
        # Crew_<random uuid>, a new behavior on every run.
        result = Crew(name="support-crew", agents=[agent], tasks=tasks, verbose=True).kickoff()
        print("\n=== crew finished ===")
        print(result)
