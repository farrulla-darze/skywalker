"""Agent discovery — scans .skywalker/agents/*.yml and returns validated configs."""

import logging
from pathlib import Path
from typing import List

import yaml

from .schemas import YAMLAgentConfig

logger = logging.getLogger(__name__)


class AgentLoader:
    """Discovers YAML agent definitions from a directory."""

    def __init__(self, agents_dir: str | Path):
        """Initialize loader.

        Args:
            agents_dir: Path to the directory containing .yml agent files.
        """
        self.agents_dir = Path(agents_dir)

    def discover(self) -> List[YAMLAgentConfig]:
        """Scan the agents directory and return validated configs.

        Returns:
            List of validated YAMLAgentConfig instances.

        Raises:
            FileNotFoundError: If the agents directory doesn't exist.
            ValueError: If a YAML file fails validation.
        """
        if not self.agents_dir.exists():
            logger.warning(
                "Agents directory not found: %s (no agents will be loaded)",
                self.agents_dir,
            )
            return []

        configs: List[YAMLAgentConfig] = []
        for yml_path in sorted(self.agents_dir.glob("*.yml")):
            try:
                raw = yaml.safe_load(yml_path.read_text())
                if raw is None:
                    logger.warning("Skipping empty YAML file: %s", yml_path.name)
                    continue
                config = YAMLAgentConfig(**raw)
                configs.append(config)
                logger.debug(
                    "Loaded agent from %s: name=%s, tools=%s",
                    yml_path.name,
                    config.name,
                    config.tools.include if config.tools.include else "[]",
                )
            except Exception as e:
                logger.error(
                    "Failed to load agent from %s: %s",
                    yml_path.name,
                    str(e),
                    exc_info=True,
                )
                continue

        return configs



if __name__ == "__main__":
    loader = AgentLoader(".skywalker/agents")
    configs = loader.discover()
    print(configs)