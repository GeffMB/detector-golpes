"""Detector de golpes on-chain para tokens da Solana."""
from .checagens import analisar, calcular_nota, classificar
from .fontes import Dados, TokenInvalido, coletar

__all__ = ["analisar", "calcular_nota", "classificar", "coletar", "Dados", "TokenInvalido"]
__version__ = "0.1.0"
