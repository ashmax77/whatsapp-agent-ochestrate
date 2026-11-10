from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from app.state.session import Session


class BaseAgent(ABC):
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def run(self, message: str, session: Session, **kwargs) -> Dict[str, Any]:
        """
        Executes the agent's logic on incoming message.
        """
        pass

