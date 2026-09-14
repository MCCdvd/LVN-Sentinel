from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeConfig:
    data_dir: str = str(REPO_ROOT / "data")
    output_dir: str = str(REPO_ROOT / "database" / "single_ticker_analysis")


@dataclass(frozen=True)
class StrategyConfig:
    investimento_per_trade: float = 10000.0
    commissione_apertura: float = 10.0
    commissione_chiusura: float = 10.0
    window_profile: int = 25
    price_tolerance: float = 0.05
    lvn_threshold: float = 0.50
    bin_step: float = 0.05
    min_profile_levels: int = 5
    rsi_period: int = 14
    rsi_long_max: float = 35.0
    rsi_short_min: float = 65.0


@dataclass(frozen=True)
class GridConfig:
    window_profiles: List[int] = field(default_factory=lambda: [12, 15, 18, 20])
    price_tolerances: List[float] = field(default_factory=lambda: [0.15, 0.18, 0.20, 0.22, 0.25])
    lvn_thresholds: List[float] = field(default_factory=lambda: [0.25, 0.30, 0.35, 0.40])
    top_n: int = 20


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    grid: GridConfig = field(default_factory=GridConfig)


CONFIG = AppConfig()

