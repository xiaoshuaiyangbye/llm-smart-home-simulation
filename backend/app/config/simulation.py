from pydantic import BaseModel, Field


class SimulationConfig(BaseModel):
    """Deterministic defaults for research-grade simulation runs."""

    seed: int = 42
    tick_minutes: int = Field(default=5, ge=1)
    max_ticks: int = Field(default=288, ge=1)
    log_run_id: str = "research-demo"

