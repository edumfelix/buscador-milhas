from __future__ import annotations

DESTINATIONS: dict[str, dict[str, str]] = {
    "GRU": {"city": "São Paulo", "country": "Brasil", "region": "Sudeste"},
    "GIG": {"city": "Rio de Janeiro", "country": "Brasil", "region": "Sudeste"},
    "BSB": {"city": "Brasília", "country": "Brasil", "region": "Centro-Oeste"},
    "SSA": {"city": "Salvador", "country": "Brasil", "region": "Nordeste"},
    "REC": {"city": "Recife", "country": "Brasil", "region": "Nordeste"},
    "NAT": {"city": "Natal", "country": "Brasil", "region": "Nordeste"},
    "BEL": {"city": "Belém", "country": "Brasil", "region": "Norte"},
    "MAO": {"city": "Manaus", "country": "Brasil", "region": "Norte"},
    "POA": {"city": "Porto Alegre", "country": "Brasil", "region": "Sul"},
    "VCP": {"city": "Campinas", "country": "Brasil", "region": "Sudeste"},
    "FLN": {"city": "Florianópolis", "country": "Brasil", "region": "Sul"},
    "CWB": {"city": "Curitiba", "country": "Brasil", "region": "Sul"},
    "MIA": {"city": "Miami", "country": "Estados Unidos", "region": "América do Norte"},
    "MCO": {"city": "Orlando", "country": "Estados Unidos", "region": "América do Norte"},
    "JFK": {"city": "Nova York", "country": "Estados Unidos", "region": "América do Norte"},
    "LIS": {"city": "Lisboa", "country": "Portugal", "region": "Europa"},
    "MAD": {"city": "Madri", "country": "Espanha", "region": "Europa"},
    "CDG": {"city": "Paris", "country": "França", "region": "Europa"},
    "AMS": {"city": "Amsterdã", "country": "Países Baixos", "region": "Europa"},
    "LHR": {"city": "Londres", "country": "Reino Unido", "region": "Europa"},
    "DXB": {"city": "Dubai", "country": "Emirados Árabes", "region": "Oriente Médio"},
    "DOH": {"city": "Doha", "country": "Catar", "region": "Oriente Médio"},
    "EZE": {"city": "Buenos Aires", "country": "Argentina", "region": "América do Sul"},
    "SCL": {"city": "Santiago", "country": "Chile", "region": "América do Sul"},
    "BOG": {"city": "Bogotá", "country": "Colômbia", "region": "América do Sul"},
    "LIM": {"city": "Lima", "country": "Peru", "region": "América do Sul"},
    "CUN": {"city": "Cancún", "country": "México", "region": "América do Norte"},
    "PTY": {"city": "Cidade do Panamá", "country": "Panamá", "region": "América Central"},
}


def destination_city(code: str) -> str:
    item = DESTINATIONS.get(code.upper())
    return item["city"] if item else code.upper()


def destination_country(code: str) -> str:
    item = DESTINATIONS.get(code.upper())
    return item["country"] if item else ""


def destination_name(code: str) -> str:
    city = destination_city(code)
    return f"{city} ({code.upper()})" if city != code.upper() else code.upper()
