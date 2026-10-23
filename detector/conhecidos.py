"""Tokens conhecidos cujas permissões de emissão e congelamento são esperadas.

Stablecoins reguladas precisam emitir tokens quando recebem depósitos e
congelar carteiras por exigência legal. Nelas, essas permissões não indicam golpe.

Só entram aqui tokens com emissor identificado e regulado. Confira o endereço
oficial no site do emissor antes de adicionar qualquer item.
"""

EMISSORES_REGULADOS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USD Coin (USDC)", "Circle"),
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": ("Tether (USDT)", "Tether"),
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": ("PayPal USD (PYUSD)", "Paxos / PayPal"),
}


def emissor_regulado(mint: str) -> tuple[str, str] | None:
    return EMISSORES_REGULADOS.get(mint)
