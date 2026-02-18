"""Context assembly for Skywalker agents."""

from typing import Dict, List
from .session import Message
from .workspace import WorkspaceManager


class ContextBuilder:
    """Builds context for agent runs."""

    def __init__(self, workspace_manager: WorkspaceManager):
        """Initialize context builder.

        Args:
            workspace_manager: Workspace manager instance.
        """
        self.workspace_manager = workspace_manager

    def build_context(
        self,
        messages: List[Message],
        system_prompt: str,
        include_bootstrap: bool = True,
    ) -> List[Dict[str, str]]:
        """Build context messages for an agent run.

        Args:
            messages: Conversation history (from JSONL).
            system_prompt: System prompt text.
            include_bootstrap: Whether to include bootstrap files.

        Returns:
            List of message dictionaries for the model.
        """
        ctx: List[Dict[str, str]] = []

        ctx.append({
            "role": "system",
            "content": system_prompt,
        })

        for msg in messages:
            if msg.role in ("user", "assistant"):
                ctx.append({
                    "role": msg.role,
                    "content": msg.content,
                })
            elif msg.role == "tool" and msg.tool_results:
                for result in msg.tool_results:
                    ctx.append({
                        "role": "assistant",
                        "content": (
                            f"Tool: {result.get('tool_name', 'unknown')}\n"
                            f"Result: {result.get('result', '')}"
                        ),
                    })

        return ctx

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (~4 characters per token)."""
        return len(text) // 4

    def get_context_stats(
        self,
        messages: List[Message],
        system_prompt: str,
    ) -> Dict[str, int]:
        """Get context statistics."""
        system_tokens = self.estimate_tokens(system_prompt)

        history_text = ""
        for msg in messages:
            history_text += msg.content + "\n"
        history_tokens = self.estimate_tokens(history_text)

        return {
            "system_tokens": system_tokens,
            "history_tokens": history_tokens,
            "total_tokens": system_tokens + history_tokens,
            "message_count": len(messages),
        }
