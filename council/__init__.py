"""An AI council: several NVIDIA-hosted models debate, a chair rules."""

from .config import CouncilConfig, Seat, load_config
from .protocol import deliberate

__all__ = ["CouncilConfig", "Seat", "load_config", "deliberate"]
