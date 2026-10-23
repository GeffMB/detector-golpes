# Detector de Golpes — Solana

Analisa um token da Solana e devolve uma **nota de risco de 0 a 100**, com cada sinal explicado em português.

> Análise automática de sinais técnicos. Não é recomendação de compra ou venda.

## Como rodar no Windows

1. Instale o Python 3.10 ou mais novo (marque "Add Python to PATH").
2. Abra o terminal (PowerShell) nesta pasta e rode:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

3. Analise um token:

```powershell
python analisar.py EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
python analisar.py <endereço> --json
```

4. Rode os testes:

```powershell
python -m pytest -q
```

### Atualizar para a versão mais recente

```powershell
powershell -ExecutionPolicy Bypass -File atualizar.ps1
```

### RPC recomendado (grátis)

O RPC público da Solana tem limite baixo e às vezes recusa consultas de detentores.
Crie uma chave grátis na [Helius](https://www.helius.dev) e configure:

```powershell
$env:SOLANA_RPC_URL = "https://mainnet.helius-rpc.com/?api-key=SUA_CHAVE"
```

## O que é verificado (versão 1)

| Sinal | Peso | Fonte |
| --- | --- | --- |
| Emissão de novos tokens (mint authority) | 20 | RPC da Solana |
| Congelamento de carteiras (freeze authority) | 15 | RPC da Solana |
| Liquidez travada ou queimada (< 80% = risco) | 15 | RugCheck |
| Top 10 carteiras com mais de 30% do supply | 15 | RPC da Solana |
| Nome e imagem alteráveis | 5 | RugCheck |
| Pool com menos de 24 horas | 5 | DexScreener |

- A nota é calculada **só sobre o que foi verificado**. Se uma fonte falhar, o sinal aparece como `[?]` e a **cobertura** mostra quanto da análise foi feita.
- Contas de programa (pools, bonding curves, cofres) **não contam** como concentração: só carteiras de pessoas.
- **Stablecoins reguladas** (USDC, USDT, PYUSD, em `detector/conhecidos.py`) têm emissão e congelamento ativos por exigência legal: esses sinais aparecem como `[i]` (informativo) e ficam fora da nota.
- **Pools maduros** (mais de US$ 1 milhão e mais de 30 dias) dispensam a trava de liquidez: com tantos provedores, ninguém retira tudo de uma vez.
- A idade usa o **pool mais antigo** do token, e o RPC tenta de novo automaticamente quando recusa por excesso de consultas.
- Classificação: 0–20 risco baixo · 21–50 risco médio · 51–100 risco alto.

## Estrutura

```
analisar.py            linha de comando
detector/fontes.py     coleta dados (RPC, RugCheck, DexScreener) em paralelo
detector/checagens.py  regras, pesos e cálculo da nota
detector/relatorio.py  relatório em texto e JSON
tests/                 testes com respostas simuladas das APIs
```

## Próximas versões

- v2: compras em bundle no lançamento (peso 15) e histórico do criador (peso 10)
- API com cache (Cloudflare) e site
- Bot do Telegram
