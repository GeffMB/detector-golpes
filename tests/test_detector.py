import asyncio
import json
import time

import httpx
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from detector.checagens import (PESOS, analisar, calcular_nota, checar_concentracao, checar_idade,
                                checar_liquidez, classificar)
from detector import fontes
from detector.fontes import Dados, TokenInvalido, coletar
from detector.relatorio import como_texto

MINT = "So11111111111111111111111111111111111111112"
CARTEIRA = [str(Keypair().pubkey()) for _ in range(12)]          # donos comuns (on-curve)
POOL = str(Pubkey.find_program_address([b"pool"], Pubkey.default())[0])  # conta de programa (off-curve)
AGORA = int(time.time() * 1000)


def dados_bons(**kw) -> Dados:
    d = Dados(
        mint=MINT,
        token={"programa": "x", "mint_authority": None, "freeze_authority": None, "supply": 1_000_000, "decimais": 6},
        detentores=[{"conta": f"c{i}", "dono": CARTEIRA[i], "quantidade": 10_000} for i in range(12)],
        rugcheck={"lpLockedPct": 100, "risks": [], "score_normalised": 5},
        mercado={"liquidez_usd": 250_000, "criado_em_ms": AGORA - 30 * 86_400_000, "nome": "Teste", "simbolo": "TST"},
    )
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_token_limpo_tem_nota_zero():
    sinais = analisar(dados_bons())
    assert all(s.status == "ok" for s in sinais), sinais
    nota, cobertura = calcular_nota(sinais)
    assert (nota, cobertura) == (0, 100)
    assert classificar(nota) == "RISCO BAIXO"


def test_data_no_futuro_nao_quebra():
    d = dados_bons(mercado={"liquidez_usd": 9000, "criado_em_ms": AGORA + 3_600_000})
    assert checar_idade(d, agora_ms=AGORA).status == "nao_verificado"


def test_golpe_classico_tem_risco_alto():
    d = dados_bons(
        token={"programa": "x", "mint_authority": "abc", "freeze_authority": "abc", "supply": 1_000_000, "decimais": 6},
        rugcheck={"lpLockedPct": 0, "risks": [{"name": "Mutable metadata", "level": "warn"}]},
        detentores=[{"conta": "c0", "dono": CARTEIRA[0], "quantidade": 700_000}],
    )
    sinais = analisar(d)
    sinais[-1] = checar_idade(d, agora_ms=AGORA)
    nota, _ = calcular_nota(sinais)
    assert nota >= 90
    assert classificar(nota) == "RISCO ALTO"


def test_pool_nao_conta_como_concentracao():
    d = dados_bons(detentores=[{"conta": "p", "dono": POOL, "quantidade": 800_000}] +
                   [{"conta": f"c{i}", "dono": CARTEIRA[i], "quantidade": 10_000} for i in range(12)])
    s = checar_concentracao(d)
    assert s.status == "ok"          # 10 carteiras x 1% = 10%
    assert "contas de programa" in s.detalhe


def test_fonte_falhando_fica_fora_da_nota():
    d = dados_bons(rugcheck=None)
    d.erros["rugcheck"] = "a fonte demorou demais para responder"
    sinais = analisar(d)
    nao_verif = [s.codigo for s in sinais if s.status == "nao_verificado"]
    assert set(nao_verif) == {"liquidez", "metadados"}
    _, cobertura = calcular_nota(sinais)
    assert cobertura == round(100 * (sum(PESOS.values()) - 20) / sum(PESOS.values()))


def test_sem_pool_indica_bonding_curve():
    s = checar_liquidez(dados_bons(mercado=None, sem_pool=True))
    assert s.status == "nao_verificado" and "bonding curve" in s.detalhe


def test_token_novo_e_sinal_de_risco():
    d = dados_bons(mercado={"liquidez_usd": 9000, "criado_em_ms": AGORA - 3 * 3_600_000})
    assert checar_idade(d, agora_ms=AGORA).status == "risco"


def test_relatorio_texto_em_portugues():
    texto = como_texto(dados_bons(), analisar(dados_bons()))
    assert "NOTA DE RISCO" in texto and "recomendação de compra" in " ".join(texto.split())


USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _cenario_usdc(mint):
    """Reproduz o resultado real do USDC: emissão e congelamento ativos, 0% de LP travada,
    mas liquidez enorme, espalhada e antiga."""
    return dados_bons(
        mint=mint,
        token={"programa": "x", "mint_authority": "circle", "freeze_authority": "circle",
               "supply": 1_000_000, "decimais": 6},
        rugcheck={"lpLockedPct": 0, "risks": [], "score_normalised": 1},
        mercado={"liquidez_usd": 40_000_000, "liquidez_total_usd": 300_000_000, "num_pools": 120,
                 "criado_em_ms": AGORA - 900 * 86_400_000, "nome": "USD Coin", "simbolo": "USDC"},
    )


def test_usdc_nao_e_falso_positivo():
    sinais = {s.codigo: s for s in analisar(_cenario_usdc(USDC))}
    assert sinais["mint"].status == "info" and "Circle" in sinais["mint"].detalhe
    assert sinais["freeze"].status == "info"
    assert sinais["liquidez"].status == "info"
    nota, cobertura = calcular_nota(list(sinais.values()))
    assert classificar(nota) == "RISCO BAIXO"
    assert cobertura == 100


def test_usdc_real_sem_data_e_sem_concentracao():
    """Reproduz a saída real do usuário em 23/10: pools sem data e RPC recusando os detentores."""
    d = _cenario_usdc(USDC)
    d.mercado = {"liquidez_usd": 40_000_000, "liquidez_total_usd": 300_000_000, "num_pools": 30,
                 "criado_em_ms": None, "nome": "USD Coin", "simbolo": "USDC"}
    d.detentores = None
    d.erros["detentores"] = "limite de consultas atingido; tente de novo em instantes"
    sinais = {s.codigo: s for s in analisar(d)}
    assert sinais["liquidez"].status == "info"
    assert sinais["idade"].status == "info"
    nota, _ = calcular_nota(list(sinais.values()))
    assert classificar(nota) == "RISCO BAIXO"


def test_usdc_com_helius_contas_demais():
    """Saída real com Helius: o RPC recusa listar detentores de tokens com 10 milhões+ de contas."""
    d = _cenario_usdc(USDC)
    d.detentores = None
    d.erros["detentores"] = "RPC: Too many accounts requested (10000000 pubkeys), try adding filters"
    s = checar_concentracao(d)
    assert s.status == "info" and "milhões de detentores" in s.detalhe
    nota, cobertura = calcular_nota(analisar(d))
    assert (nota, cobertura) == (0, 100)


def test_token_comum_com_contas_demais_explica_o_motivo():
    d = dados_bons(detentores=None)
    d.erros["detentores"] = "RPC: Too many accounts requested (10000000 pubkeys)"
    s = checar_concentracao(d)
    assert s.status == "nao_verificado" and "muito grandes" in s.detalhe


def test_token_sem_data_com_muitos_pools_grandes_e_maduro():
    d = dados_bons(rugcheck={"lpLockedPct": 0, "risks": []},
                   mercado={"liquidez_total_usd": 50_000_000, "num_pools": 25, "criado_em_ms": None})
    assert checar_liquidez(d).status == "ok"


def test_token_sem_data_com_poucos_pools_continua_exigindo_trava():
    d = dados_bons(rugcheck={"lpLockedPct": 0, "risks": []},
                   mercado={"liquidez_total_usd": 2_000_000, "num_pools": 2, "criado_em_ms": None})
    assert checar_liquidez(d).status == "risco"


def test_memecoin_com_as_mesmas_permissoes_continua_alto():
    d = _cenario_usdc(CARTEIRA[0])  # endereço qualquer, fora da lista de emissores regulados
    d.mercado = {"liquidez_usd": 8_000, "liquidez_total_usd": 8_000, "num_pools": 1,
                 "criado_em_ms": AGORA - 5 * 3_600_000}
    nota, _ = calcular_nota(analisar(d))
    assert classificar(nota) == "RISCO ALTO"


def test_pool_grande_mas_novo_ainda_exige_trava():
    d = dados_bons(rugcheck={"lpLockedPct": 10, "risks": []},
                   mercado={"liquidez_total_usd": 2_000_000, "num_pools": 2,
                            "criado_em_ms": AGORA - 2 * 86_400_000})
    assert checar_liquidez(d).status == "risco"


def test_relatorio_identifica_token_conhecido():
    texto = como_texto(_cenario_usdc(USDC), analisar(_cenario_usdc(USDC)))
    assert "Token conhecido: USD Coin (USDC)" in texto and "[i]" in texto


# ---------- coletores com respostas simuladas das APIs ----------

def _transporte(mint_info=True, rugcheck_status=200, rpc_429=0):
    falhas = {"restantes": rpc_429}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "rpc.teste" and falhas["restantes"] > 0:
            falhas["restantes"] -= 1
            return httpx.Response(429)
        if "rugcheck" in req.url.host:
            if rugcheck_status != 200:
                return httpx.Response(rugcheck_status)
            return httpx.Response(200, json={"lpLockedPct": 95.5, "risks": [], "score_normalised": 3})
        if "dexscreener" in req.url.host:
            return httpx.Response(200, json=[
                {"dexId": "raydium", "pairAddress": "p1", "liquidity": {"usd": 1000}, "pairCreatedAt": 1},
                {"dexId": "pumpswap", "pairAddress": "p2", "liquidity": {"usd": 90000}, "pairCreatedAt": 2,
                 "baseToken": {"name": "Gato", "symbol": "GATO"}},
            ])
        corpo = json.loads(req.content)
        m = corpo["method"]
        if m == "getAccountInfo":
            if not mint_info:
                return httpx.Response(200, json={"result": {"value": None}})
            return httpx.Response(200, json={"result": {"value": {"owner": "TokenkegQ", "data": {"parsed": {
                "type": "mint", "info": {"mintAuthority": None, "freezeAuthority": "F1", "supply": "1000", "decimals": 6}}}}}})
        if m == "getTokenLargestAccounts":
            return httpx.Response(200, json={"result": {"value": [{"address": "a1", "amount": "500"}]}})
        if m == "getMultipleAccounts":
            return httpx.Response(200, json={"result": {"value": [
                {"data": {"parsed": {"info": {"owner": CARTEIRA[0]}}}}]}})
        return httpx.Response(400)
    return httpx.MockTransport(handler)


def _coletar(**kw):
    async def run():
        async with httpx.AsyncClient(transport=_transporte(**kw)) as c:
            return await coletar(MINT, rpc="https://rpc.teste", client=c)
    return asyncio.run(run())


def test_coletar_monta_os_dados():
    d = _coletar()
    assert d.token["freeze_authority"] == "F1" and d.token["supply"] == 1000
    assert d.detentores[0]["dono"] == CARTEIRA[0]
    assert d.mercado["dex"] == "pumpswap"          # escolhe o pool com mais liquidez
    assert d.mercado["criado_em_ms"] == 1          # idade = pool mais antigo
    assert d.mercado["liquidez_total_usd"] == 91000 and d.mercado["num_pools"] == 2
    assert d.rugcheck["lpLockedPct"] == 95.5
    assert d.erros == {}


def test_coletar_endereco_inexistente():
    with pytest.raises(TokenInvalido):
        _coletar(mint_info=False)


def test_rpc_tenta_de_novo_depois_de_limite(monkeypatch):
    monkeypatch.setattr(fontes, "ESPERAS_429", (0, 0))
    d = _coletar(rpc_429=2)                        # duas recusas seguidas, depois responde
    assert d.token is not None and d.detentores is not None
    assert d.erros == {}


def test_coletar_sobrevive_a_falha_de_uma_fonte():
    d = _coletar(rugcheck_status=429)
    assert d.rugcheck is None
    assert "limite de consultas" in d.erros["rugcheck"]
    assert d.token is not None
