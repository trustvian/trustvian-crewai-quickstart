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
# at e.g. openai/gpt-4o-mini to use OpenAI instead (OPENAI_API_KEY required).
llm = LLM(
    model=os.environ.get("LLM_MODEL", "ollama/gemma3:4b"),
    base_url=os.environ.get("LLM_BASE_URL", "http://localhost:11434"),
    temperature=0.2,
)

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
    result = Crew(agents=[agent], tasks=tasks, verbose=True).kickoff()
    print("\n=== crew finished ===")
    print(result)
