"""Uso:  python analisar.py <endereço_do_token> [--json] [--rpc URL]

Exemplo:
    python analisar.py EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

from detector.checagens import analisar
from detector.fontes import RPC_PADRAO, TokenInvalido, coletar
from detector.relatorio import como_dict, como_texto

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # acentos corretos no terminal do Windows
    p = argparse.ArgumentParser(description="Detector de golpes para tokens da Solana")
    p.add_argument("mint", help="endereço (mint) do token")
    p.add_argument("--json", action="store_true", help="saída em JSON")
    p.add_argument("--rpc", default=os.getenv("SOLANA_RPC_URL", RPC_PADRAO),
                   help="URL do RPC da Solana (padrão: variável SOLANA_RPC_URL ou RPC público)")
    a = p.parse_args()

    if not BASE58.match(a.mint):
        print("Endereço inválido: um endereço da Solana tem de 32 a 44 caracteres em base58.")
        return 2
    try:
        dados = asyncio.run(coletar(a.mint, rpc=a.rpc))
    except TokenInvalido as e:
        print(f"Não foi possível analisar: {e}")
        return 2
    sinais = analisar(dados)
    print(json.dumps(como_dict(dados, sinais), ensure_ascii=False, indent=2) if a.json
          else como_texto(dados, sinais))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
