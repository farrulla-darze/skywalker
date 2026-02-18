"""Agent guardrail manager — validates inputs/outputs using LLM-based guardrails."""

import logging
from typing import Optional

from pydantic_ai import Agent as PydanticAgent

from .schemas import AgentGuardrailResponse
from .context_manager.guardrail_prompts import (
    get_input_guardrail_prompt,
    get_output_guardrail_prompt,
)
from ..core.config import Config

logger = logging.getLogger(__name__)


class AgentGuardrailManager:
    """Manages input and output guardrails using LLM validation.

    Guardrails act as safety filters that:
    1. Validate user inputs before processing
    2. Validate agent outputs before sending to users
    3. Prevent prompt injection and malicious content
    4. Enforce content policies and safety boundaries

    Uses a lightweight LLM (e.g., GPT-3.5) for fast validation.
    """

    def __init__(self, config: Config, guardrail_model: Optional[str] = None):
        """Initialize the guardrail manager.

        Args:
            config: Global configuration.
            guardrail_model: Optional model override for guardrails (defaults to fast model).
        """
        self.config = config

        # Use a fast, cheap model for guardrails
        self.guardrail_model = guardrail_model or "openai:gpt-4o-mini"

        # Normalize model string
        if "/" in self.guardrail_model and ":" not in self.guardrail_model:
            self.guardrail_model = self.guardrail_model.replace("/", ":", 1)

        logger.info("AgentGuardrailManager initialized: model=%s", self.guardrail_model)

    async def validate_input(
        self,
        user_message: str,
        user_id: str,
        session_id: str,
    ) -> AgentGuardrailResponse:
        """Validate user input before processing.

        Uses LLM to check for:
        - Prompt injection attempts
        - Malicious content
        - Off-topic queries
        - Inappropriate requests

        Args:
            user_message: User's input message.
            user_id: User identifier.
            session_id: Session identifier.

        Returns:
            AgentGuardrailResponse with approval status and optional rejection message.
        """
        logger.info(
            "Validating input: user_id=%s, session_id=%s, message_length=%d",
            user_id,
            session_id,
            len(user_message),
        )

        try:
            # Build guardrail prompt
            prompt = get_input_guardrail_prompt(user_message, user_id, session_id)

            # Create lightweight guardrail agent
            guardrail_agent = PydanticAgent(
                model=self.guardrail_model,
                system_prompt="You are a content safety validator. Respond concisely.",
            )

            # Run validation
            result = await guardrail_agent.run(prompt)
            response_text = result.output if hasattr(result, "output") else str(result)

            # Parse response
            if response_text.startswith("APPROVED"):
                # Extract reason
                reason = response_text.replace("APPROVED:", "").strip()
                logger.info("Input approved: user_id=%s, reason=%s", user_id, reason)
                return AgentGuardrailResponse(
                    approved=True,
                    reason=reason,
                    response=None,
                )

            elif response_text.startswith("REJECTED"):
                # Parse rejection: REJECTED: [reason] | RESPONSE: [message]
                parts = response_text.split("|")
                reason = parts[0].replace("REJECTED:", "").strip()

                # Extract pre-composed response
                rejection_message = "I'm here to help with CloudWalk support. How can I assist you?"
                if len(parts) > 1 and "RESPONSE:" in parts[1]:
                    rejection_message = parts[1].split("RESPONSE:")[1].strip()

                logger.warning(
                    "Input rejected: user_id=%s, reason=%s",
                    user_id,
                    reason,
                )

                return AgentGuardrailResponse(
                    approved=False,
                    reason=reason,
                    response=rejection_message,
                )

            else:
                # Unexpected format - default to approval but log warning
                logger.warning(
                    "Guardrail returned unexpected format: %s",
                    response_text[:100],
                )
                return AgentGuardrailResponse(
                    approved=True,
                    reason="Unexpected guardrail format - defaulting to approval",
                    response=None,
                )

        except Exception as e:
            logger.error(
                "Guardrail validation failed: user_id=%s, error=%s",
                user_id,
                str(e),
                exc_info=True,
            )
            # Fail open - allow the request but log the error
            return AgentGuardrailResponse(
                approved=True,
                reason=f"Guardrail error (fail-open): {str(e)}",
                response=None,
            )

    async def validate_output(
        self,
        agent_response: str,
        user_message: str,
        user_id: str,
    ) -> AgentGuardrailResponse:
        """Validate agent output before sending to user.

        Uses LLM to check for:
        - Sensitive data leakage
        - Internal system details exposure
        - Inappropriate content
        - Policy violations

        Args:
            agent_response: Agent's generated response.
            user_message: Original user message.
            user_id: User identifier.

        Returns:
            AgentGuardrailResponse with approval status and optional revised response.
        """
        logger.info(
            "Validating output: user_id=%s, response_length=%d",
            user_id,
            len(agent_response),
        )

        try:
            # Build guardrail prompt
            prompt = get_output_guardrail_prompt(agent_response, user_message)

            # Create lightweight guardrail agent
            guardrail_agent = PydanticAgent(
                model=self.guardrail_model,
                system_prompt="You are a content safety validator. Respond concisely.",
            )

            # Run validation
            result = await guardrail_agent.run(prompt)
            response_text = result.output if hasattr(result, "output") else str(result)

            # Parse response
            if response_text.startswith("APPROVED"):
                reason = response_text.replace("APPROVED:", "").strip()
                logger.info("Output approved: user_id=%s, reason=%s", user_id, reason)
                return AgentGuardrailResponse(
                    approved=True,
                    reason=reason,
                    response=None,
                )

            elif response_text.startswith("REJECTED"):
                # Parse rejection: REJECTED: [reason] | REVISED: [safer response]
                parts = response_text.split("|")
                reason = parts[0].replace("REJECTED:", "").strip()

                # Extract revised response
                revised_response = agent_response  # Fallback to original
                if len(parts) > 1 and "REVISED:" in parts[1]:
                    revised_response = parts[1].split("REVISED:")[1].strip()

                logger.warning(
                    "Output rejected and revised: user_id=%s, reason=%s",
                    user_id,
                    reason,
                )

                return AgentGuardrailResponse(
                    approved=False,
                    reason=reason,
                    response=revised_response,
                )

            else:
                # Unexpected format - default to approval
                logger.warning(
                    "Guardrail returned unexpected format: %s",
                    response_text[:100],
                )
                return AgentGuardrailResponse(
                    approved=True,
                    reason="Unexpected guardrail format - defaulting to approval",
                    response=None,
                )

        except Exception as e:
            logger.error(
                "Output guardrail validation failed: user_id=%s, error=%s",
                user_id,
                str(e),
                exc_info=True,
            )
            # Fail open - allow the response but log the error
            return AgentGuardrailResponse(
                approved=True,
                reason=f"Guardrail error (fail-open): {str(e)}",
                response=None,
            )
