"""Langfuse prompt management.

The database stores each agent's baseline instructions (and is the fallback),
but when Langfuse is enabled the *served* prompt comes from Langfuse Prompt
Management under the name ``agent-{slug}`` with the ``production`` label:

- On startup, prompts that don't exist yet are created from the DB baseline
  (existing Langfuse versions are never overwritten — UI edits win).
- At runtime the prompt is fetched with a short cache TTL, so editing a prompt
  in the Langfuse UI and promoting it to the ``production`` label deploys it
  to the running app within ~60s — no redeploy.
- The prompt client is linked to the generations of the turn (via
  ``propagate_attributes(prompt=...)``), so Langfuse tracks quality/latency/
  cost per prompt version.
"""

import logging
from typing import Any

from app.core.tracing import is_tracing_enabled

from .models import Agent

logger = logging.getLogger(__name__)

PROMPT_LABEL = "production"
PROMPT_CACHE_TTL_SECONDS = 60


def prompt_name_for(slug: str) -> str:
    return f"agent-{slug}"


def resolve_agent_instructions(agent: Agent) -> tuple[str, Any | None]:
    """Return (instructions, langfuse_prompt_client | None) for an agent.

    Falls back to the DB instructions whenever Langfuse is disabled,
    unreachable, or serving the fallback.
    """
    if not is_tracing_enabled():
        return agent.instructions, None
    try:
        from langfuse import get_client

        prompt = get_client().get_prompt(
            prompt_name_for(agent.slug),
            label=PROMPT_LABEL,
            fallback=agent.instructions,
            cache_ttl_seconds=PROMPT_CACHE_TTL_SECONDS,
        )
        text = prompt.prompt if isinstance(prompt.prompt, str) else agent.instructions
        if getattr(prompt, "is_fallback", False):
            return text, None  # don't link generations to a fallback pseudo-version
        return text, prompt
    except Exception as exc:  # noqa: BLE001 — prompt fetch must never break a turn
        logger.warning("Langfuse prompt fetch failed for %s: %s", agent.slug, exc)
        return agent.instructions, None


async def sync_prompts_to_langfuse(agents: list[Agent]) -> None:
    """Create missing Langfuse prompts from DB baselines (never overwrites)."""
    if not is_tracing_enabled():
        return
    try:
        from langfuse import get_client

        client = get_client()
    except Exception:  # noqa: BLE001
        return

    for agent in agents:
        name = prompt_name_for(agent.slug)
        try:
            client.get_prompt(name, label=PROMPT_LABEL, cache_ttl_seconds=0, max_retries=1)
            continue  # exists — Langfuse (UI-editable) version wins
        except Exception:  # noqa: BLE001 — not found (or transient; create is idempotent-ish)
            pass
        try:
            client.create_prompt(
                name=name,
                prompt=agent.instructions,
                labels=[PROMPT_LABEL],
                type="text",
                commit_message="Initial version seeded from database baseline",
            )
            logger.info("Seeded Langfuse prompt '%s' (label=%s)", name, PROMPT_LABEL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to seed Langfuse prompt '%s': %s", name, exc)
