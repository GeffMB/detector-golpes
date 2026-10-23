"""Coletores de dados: RPC da Solana, RugCheck e DexScreener.

Cada coletor é independente. Se um falhar, os outros continuam e a
checagem correspondente aparece como "não verificado" no relatório.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

RPC_PADRAO = "https://api.mainnet-beta.solana.com"
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"
DEXSCREENER_URL = "https://api.dexscreener.com/tokens/v1/solana/{mint}"


class FonteErro(Exception):
    """Erro de uma fonte de dados, com mensagem em português."""


class TokenInvalido(Exception):
    """O endereço não existe ou não é um token."""


@dataclass
class Dados:
    mint: str
    token: dict[str, Any] | None = None          # autoridades, supply, decimais
    detentores: list[dict[str, Any]] | None = None
    rugcheck: dict[str, Any] | None = None
    mercado: dict[str, Any] | None = None        # melhor pool na DexScreener
    sem_pool: bool = False                       # DexScreener respondeu, mas sem pares
    erros: dict[str, str] = field(default_factory=dict)


ESPERAS_429 = (1.5, 4.0)  # segundos entre novas tentativas quando o RPC limita as consultas


async def _rpc(client: httpx.AsyncClient, url: str, metodo: str, params: list) -> Any:
    corpo_req = {"jsonrpc": "2.0", "id": 1, "method": metodo, "params": params}
    r = await client.post(url, json=corpo_req)
    for espera in ESPERAS_429:
        if r.status_code != 429:
            break
        await asyncio.sleep(espera)
        r = await client.post(url, json=corpo_req)
    r.raise_for_status()
    corpo = r.json()
    if "error" in corpo:
        raise FonteErro(f"RPC: {corpo['error'].get('message', 'erro desconhecido')}")
    return corpo["result"]


async def dados_do_token(client: httpx.AsyncClient, rpc: str, mint: str) -> dict[str, Any]:
    res = await _rpc(client, rpc, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    conta = res.get("value") if res else None
    if not conta:
        raise TokenInvalido("Endereço não encontrado na Solana.")
    dados = conta.get("data")
    if not isinstance(dados, dict) or dados.get("parsed", {}).get("type") != "mint":
        raise TokenInvalido("Este endereço existe, mas não é um token.")
    info = dados["parsed"]["info"]
    return {
        "programa": conta.get("owner"),
        "mint_authority": info.get("mintAuthority"),
        "freeze_authority": info.get("freezeAuthority"),
        "supply": int(info.get("supply", 0)),
        "decimais": info.get("decimals"),
    }


async def maiores_detentores(client: httpx.AsyncClient, rpc: str, mint: str) -> list[dict[str, Any]]:
    res = await _rpc(client, rpc, "getTokenLargestAccounts", [mint])
    contas = res.get("value", [])
    if not contas:
        return []
    enderecos = [c["address"] for c in contas]
    multi = await _rpc(client, rpc, "getMultipleAccounts", [enderecos, {"encoding": "jsonParsed"}])
    saida = []
    for c, conta in zip(contas, multi.get("value", [])):
        dono = None
        if conta and isinstance(conta.get("data"), dict):
            dono = conta["data"].get("parsed", {}).get("info", {}).get("owner")
        saida.append({"conta": c["address"], "dono": dono, "quantidade": int(c["amount"])})
    return saida


async def resumo_rugcheck(client: httpx.AsyncClient, mint: str) -> dict[str, Any] | None:
    r = await client.get(RUGCHECK_URL.format(mint=mint))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


async def melhor_pool(client: httpx.AsyncClient, mint: str) -> dict[str, Any] | None:
    r = await client.get(DEXSCREENER_URL.format(mint=mint))
    r.raise_for_status()
    pares = r.json() or []
    if isinstance(pares, dict):  # formato antigo: {"pairs": [...]}
        pares = pares.get("pairs") or []
    if not pares:
        return None
    liq = lambda p: (p.get("liquidity") or {}).get("usd") or 0
    melhor = max(pares, key=liq)
    datas = [p["pairCreatedAt"] for p in pares if p.get("pairCreatedAt")]
    return {
        "dex": melhor.get("dexId"),
        "par": melhor.get("pairAddress"),
        "liquidez_usd": liq(melhor) or None,
        "liquidez_total_usd": sum(liq(p) for p in pares),
        "num_pools": len(pares),
        "criado_em_ms": min(datas) if datas else None,  # pool mais antigo ≈ idade do token
        "nome": (melhor.get("baseToken") or {}).get("name"),
        "simbolo": (melhor.get("baseToken") or {}).get("symbol"),
    }


async def coletar(mint: str, rpc: str = RPC_PADRAO, timeout: float = 15.0,
                  client: httpx.AsyncClient | None = None) -> Dados:
    """Busca tudo em paralelo. Lança TokenInvalido se o endereço não for um token."""
    dono_do_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "detector-golpes/0.1"})
    dados = Dados(mint=mint)
    try:
        tarefas = {
            "token": dados_do_token(client, rpc, mint),
            "detentores": maiores_detentores(client, rpc, mint),
            "rugcheck": resumo_rugcheck(client, mint),
            "mercado": melhor_pool(client, mint),
        }
        resultados = await asyncio.gather(*tarefas.values(), return_exceptions=True)
        for nome, res in zip(tarefas, resultados):
            if isinstance(res, TokenInvalido):
                raise res
            if isinstance(res, Exception):
                dados.erros[nome] = _mensagem(res)
                continue
            setattr(dados, nome, res)
            if nome == "mercado" and res is None:
                dados.sem_pool = True
    finally:
        if dono_do_client:
            await client.aclose()
    return dados


def _mensagem(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 429:
            return "limite de consultas atingido; tente de novo em instantes"
        return f"a fonte respondeu com erro {e.response.status_code}"
    if isinstance(e, httpx.TimeoutException):
        return "a fonte demorou demais para responder"
    if isinstance(e, httpx.HTTPError):
        return "não foi possível conectar à fonte"
    return str(e) or e.__class__.__name__
