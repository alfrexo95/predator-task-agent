import os
from basedagents import register_or_load

name = os.getenv("AGENT_NAME", "PredatorTaskAgent")

agent_id = register_or_load(
    name=name,
    description="AI agent for research, coding and digital task execution.",
    capabilities=["reasoning", "code", "research"],
)

print("Agent identity:", agent_id)
print("Registration completed.")
