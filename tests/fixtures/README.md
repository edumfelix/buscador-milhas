# Fixtures

Respostas reais capturadas no spike devem ser salvas aqui **sanitizadas**:

- sem cookies, `authorization`, tokens ou `set-cookie`;
- sem CPF, e-mail, número de programa ou nome de passageiro;
- sem IP real (substituir por `203.0.113.1`).

Sugestão de nomes:

- `smiles_search_200_min.json`
- `smiles_406.json`
- `azul_availability_200_min.json`
- `azul_403_block.html`
- `latam_redirect.html`

Os parsers devem ser testados com essas fixtures, sem rede.
