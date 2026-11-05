from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseDatabaseCollector(ABC):
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.enabled = config.get("enabled", True)
        self.timeout = config.get("timeout", 3.0)

    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        """Collects database health, latency, connections, and size.
        Must handle exceptions gracefully and never raise.
        """
        pass

