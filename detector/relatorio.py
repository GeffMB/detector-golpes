"""Monta o relatório final em texto (terminal) ou dicionário (JSON / API)."""
from __future__ import annotations

from dataclasses import asdict

from .checagens import Sinal, calcular_nota, classificar
from .fontes import Dados

ICONES = {"risco": "[!]", "ok": "[ok]", "nao_verificado": "[?]"}
AVISO = ("Isto é uma análise automática de sinais técnicos, não uma recomendação de compra ou venda. "
         "Uma nota baixa não garante que o token seja seguro.")


def como_dict(d: Dados, sinais: list[Sinal]) -> dict:
    nota, cobertura = calcular_nota(sinais)
    rc = d.rugcheck or {}
    return {
        "mint": d.mint,
        "nome": (d.mercado or {}).get("nome"),
        "simbolo": (d.mercado or {}).get("simbolo"),
        "nota": nota,
        "classificacao": classificar(nota),
        "cobertura_pct": cobertura,
        "sinais": [asdict(s) for s in sinais],
        "referencia_rugcheck": rc.get("score_normalised"),
        "alertas_rugcheck": [r.get("name") for r in rc.get("risks") or [] if r.get("level") == "danger"],
        "erros_fontes": d.erros,
        "aviso": AVISO,
    }


def como_texto(d: Dados, sinais: list[Sinal]) -> str:
    r = como_dict(d, sinais)
    nome = " ".join(x for x in [r["nome"], f"({r['simbolo']})" if r["simbolo"] else None] if x) or "Token"
    linhas = [
        "=" * 64,
        f"  {nome}",
        f"  {d.mint}",
        "=" * 64,
    ]
    if r["nota"] is None:
        linhas.append("  NOTA: indisponível (nenhuma checagem pôde ser feita)")
    else:
        linhas.append(f"  NOTA DE RISCO: {r['nota']}/100  ->  {r['classificacao']}")
    linhas.append(f"  Cobertura: {r['cobertura_pct']}% das checagens verificadas")
    if r["referencia_rugcheck"] is not None:
        linhas.append(f"  Referência RugCheck: {r['referencia_rugcheck']}/100")
    linhas.append("")
    ordem = {"risco": 0, "nao_verificado": 1, "ok": 2}
    for s in sorted(sinais, key=lambda s: (ordem[s.status], -s.peso)):
        linhas.append(f"  {ICONES[s.status]} {s.titulo} (peso {s.peso})")
        linhas.append(_quebrar(s.detalhe, 6))
        linhas.append("")
    if r["alertas_rugcheck"]:
        linhas.append("  Alertas graves da RugCheck: " + ", ".join(r["alertas_rugcheck"]))
        linhas.append("")
    linhas.append(_quebrar("Aviso: " + AVISO, 2))
    return "\n".join(linhas)


def _quebrar(texto: str, recuo: int, largura: int = 64) -> str:
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        if len(atual) + len(p) + 1 > largura - recuo:
            linhas.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
    if atual:
        linhas.append(atual)
    return "\n".join(" " * recuo + l for l in linhas)
