"""Checagens de risco e cálculo da nota.

Cada checagem devolve um Sinal com status:
  - "risco": o sinal vermelho foi encontrado (soma o peso na nota)
  - "ok": verificado e sem problema
  - "info": a permissão existe, mas é esperada para este token (fica fora da nota)
  - "nao_verificado": a fonte falhou ou não há dado suficiente (fica fora da nota)

A nota vai de 0 (nenhum sinal de risco) a 100 (todos os sinais de risco),
calculada só sobre as checagens que puderam ser verificadas.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .conhecidos import emissor_regulado
from .fontes import Dados

try:  # solders permite saber se um dono é carteira comum ou conta de programa (pool, curva)
    from solders.pubkey import Pubkey

    def eh_carteira(endereco: str) -> bool | None:
        try:
            return Pubkey.from_string(endereco).is_on_curve()
        except ValueError:
            return None
except ImportError:  # pragma: no cover
    def eh_carteira(endereco: str) -> bool | None:
        return None

# Pesos da versão 1 (soma 75). Bundles (15) e histórico do criador (10) entram na versão 2.
PESOS = {
    "mint": 20,
    "freeze": 15,
    "liquidez": 15,
    "concentracao": 15,
    "metadados": 5,
    "idade": 5,
}

LIMITE_CONCENTRACAO = 30.0   # % do supply nas 10 maiores carteiras
LIMITE_LP_TRAVADA = 80.0     # % mínima da liquidez travada ou queimada
LIMITE_IDADE_H = 24          # horas
LIQUIDEZ_BAIXA_USD = 5_000
# Pools acima disto e mais velhos que isto estão espalhados entre muitos provedores:
# a trava da liquidez deixa de ser um sinal relevante.
LIQUIDEZ_MADURA_USD = 1_000_000
IDADE_MADURA_DIAS = 30


@dataclass
class Sinal:
    codigo: str
    titulo: str
    peso: int
    status: str
    detalhe: str


def _br(valor: float) -> str:
    """Formata 300000000 como 300.000.000 (padrão brasileiro)."""
    return f"{valor:,.0f}".replace(",", ".")


def _nv(codigo: str, titulo: str, motivo: str) -> Sinal:
    return Sinal(codigo, titulo, PESOS[codigo], "nao_verificado", f"Não foi possível verificar: {motivo}.")


def _info_regulado(codigo: str, titulo: str, mint: str, o_que: str) -> Sinal | None:
    conhecido = emissor_regulado(mint)
    if not conhecido:
        return None
    nome, emissor = conhecido
    return Sinal(codigo, titulo, PESOS[codigo], "info",
                 f"A permissão de {o_que} está ativa, o que é esperado: {nome} é uma stablecoin "
                 f"regulada, e a {emissor} precisa dela para operar e cumprir ordens legais.")


def _idade_dias(d: Dados, agora_ms: float | None = None) -> float | None:
    criado = (d.mercado or {}).get("criado_em_ms")
    if not criado:
        return None
    agora_ms = agora_ms if agora_ms is not None else time.time() * 1000
    return (agora_ms - criado) / 86_400_000


def checar_mint(d: Dados) -> Sinal:
    t = "Emissão de novos tokens"
    if not d.token:
        return _nv("mint", t, d.erros.get("token", "sem dados do token"))
    if d.token["mint_authority"]:
        info = _info_regulado("mint", t, d.mint, "emissão")
        if info:
            return info
        return Sinal("mint", t, PESOS["mint"], "risco",
                     "O criador ainda pode emitir tokens novos à vontade. Isso dilui quem já comprou "
                     "e permite despejar tokens recém-criados no mercado.")
    return Sinal("mint", t, PESOS["mint"], "ok",
                 "A permissão de emissão foi revogada: ninguém pode criar mais tokens.")


def checar_freeze(d: Dados) -> Sinal:
    t = "Congelamento de carteiras"
    if not d.token:
        return _nv("freeze", t, d.erros.get("token", "sem dados do token"))
    if d.token["freeze_authority"]:
        info = _info_regulado("freeze", t, d.mint, "congelamento")
        if info:
            return info
        return Sinal("freeze", t, PESOS["freeze"], "risco",
                     "O criador pode congelar sua carteira e impedir que você venda. "
                     "É o mecanismo clássico de token 'honeypot': dá para comprar, mas não sair.")
    return Sinal("freeze", t, PESOS["freeze"], "ok",
                 "A permissão de congelamento foi revogada: ninguém pode travar sua carteira.")


def checar_liquidez(d: Dados) -> Sinal:
    t = "Liquidez travada"
    if d.sem_pool:
        return _nv("liquidez", t, "nenhum pool em DEX encontrado; o token pode ainda estar "
                                  "na bonding curve de um launchpad")
    total = (d.mercado or {}).get("liquidez_total_usd") or 0
    dias = _idade_dias(d)
    if total >= LIQUIDEZ_MADURA_USD and dias is not None and dias >= IDADE_MADURA_DIAS:
        pools = (d.mercado or {}).get("num_pools") or 0
        return Sinal("liquidez", t, PESOS["liquidez"], "ok",
                     f"Há US$ {_br(total)} de liquidez em {pools} pool(s), existentes há {dias:.0f} dias. "
                     "Com liquidez desse tamanho e espalhada entre muitos provedores, ninguém consegue "
                     "retirá-la de uma vez; a trava deixa de ser relevante.")
    pct = (d.rugcheck or {}).get("lpLockedPct")
    if pct is None:
        return _nv("liquidez", t, d.erros.get("rugcheck", "a RugCheck não informou a liquidez travada"))
    extra = ""
    liq = (d.mercado or {}).get("liquidez_usd")
    if liq is not None and liq < LIQUIDEZ_BAIXA_USD:
        extra = f" A liquidez total também é baixa (US$ {_br(liq)}), então pequenas vendas mexem muito no preço."
    if pct < LIMITE_LP_TRAVADA:
        return Sinal("liquidez", t, PESOS["liquidez"], "risco",
                     f"Só {pct:.0f}% da liquidez está travada ou queimada. Quem controla o restante pode "
                     "retirar o dinheiro do pool e derrubar o preço a quase zero (rug pull)." + extra)
    return Sinal("liquidez", t, PESOS["liquidez"], "ok",
                 f"{pct:.0f}% da liquidez está travada ou queimada: o pool não pode ser retirado." + extra)


def checar_concentracao(d: Dados) -> Sinal:
    t = "Concentração nas maiores carteiras"
    if not d.detentores or not d.token:
        motivo = d.erros.get("detentores") or d.erros.get("token") or "sem lista de detentores"
        return _nv("concentracao", t, motivo)
    supply = d.token["supply"]
    if supply <= 0:
        return _nv("concentracao", t, "supply zerado")
    carteiras, programas = [], []
    for h in d.detentores:
        tipo = eh_carteira(h["dono"]) if h.get("dono") else None
        (programas if tipo is False else carteiras).append(h)
    top10 = sum(h["quantidade"] for h in carteiras[:10]) / supply * 100
    em_programas = sum(h["quantidade"] for h in programas) / supply * 100
    nota_prog = (f" Outros {em_programas:.0f}% estão em contas de programa (pools, curvas ou cofres), "
                 "que não contam como pessoas.") if em_programas >= 1 else ""
    if top10 > LIMITE_CONCENTRACAO:
        return Sinal("concentracao", t, PESOS["concentracao"], "risco",
                     f"As 10 maiores carteiras têm {top10:.0f}% do supply. Se poucas pessoas venderem juntas, "
                     "o preço desaba." + nota_prog)
    return Sinal("concentracao", t, PESOS["concentracao"], "ok",
                 f"As 10 maiores carteiras têm {top10:.0f}% do supply, uma distribuição aceitável." + nota_prog)


def checar_metadados(d: Dados) -> Sinal:
    t = "Nome e imagem alteráveis"
    if d.rugcheck is None:
        return _nv("metadados", t, d.erros.get("rugcheck", "token sem relatório na RugCheck"))
    riscos = d.rugcheck.get("risks") or []
    if any("mutable" in (r.get("name") or "").lower() for r in riscos):
        return Sinal("metadados", t, PESOS["metadados"], "risco",
                     "O criador pode trocar o nome e a imagem do token depois. Golpistas usam isso para "
                     "imitar projetos conhecidos ou apagar rastros.")
    return Sinal("metadados", t, PESOS["metadados"], "ok",
                 "Segundo a RugCheck, nome e imagem não podem mais ser alterados.")


def checar_idade(d: Dados, agora_ms: float | None = None) -> Sinal:
    t = "Idade do token"
    criado = (d.mercado or {}).get("criado_em_ms")
    if not criado:
        motivo = d.erros.get("mercado") or ("sem pool em DEX" if d.sem_pool else "data de criação desconhecida")
        return _nv("idade", t, motivo)
    agora_ms = agora_ms if agora_ms is not None else time.time() * 1000
    horas = (agora_ms - criado) / 3_600_000
    if horas < 0:
        return _nv("idade", t, "a data de criação informada está no futuro")
    if horas < LIMITE_IDADE_H:
        quanto = "menos de 1 hora" if horas < 1 else f"só {horas:.0f} hora(s)"
        return Sinal("idade", t, PESOS["idade"], "risco",
                     f"O pool tem {quanto}. Há pouco histórico para avaliar, e a maioria dos "
                     "golpes acontece nas primeiras horas.")
    dias = horas / 24
    return Sinal("idade", t, PESOS["idade"], "ok", f"O pool existe há {dias:.0f} dia(s).")


CHECAGENS = [checar_mint, checar_freeze, checar_liquidez, checar_concentracao, checar_metadados, checar_idade]


def analisar(d: Dados) -> list[Sinal]:
    return [c(d) for c in CHECAGENS]


def calcular_nota(sinais: list[Sinal]) -> tuple[int | None, int]:
    """Devolve (nota 0–100 ou None, cobertura em %)."""
    avaliados = [s for s in sinais if s.status in ("risco", "ok")]
    # "info" também conta como verificado na cobertura, mas não entra na nota
    peso_total = sum(PESOS.values())
    peso_verificado = sum(s.peso for s in sinais if s.status in ("risco", "ok", "info"))
    peso_avaliado = sum(s.peso for s in avaliados)
    cobertura = round(100 * peso_verificado / peso_total)
    if peso_avaliado == 0:
        return None, cobertura
    pontos = sum(s.peso for s in avaliados if s.status == "risco")
    return round(100 * pontos / peso_avaliado), cobertura


def classificar(nota: int | None) -> str:
    if nota is None:
        return "INDEFINIDO"
    if nota <= 20:
        return "RISCO BAIXO"
    if nota <= 50:
        return "RISCO MÉDIO"
    return "RISCO ALTO"
