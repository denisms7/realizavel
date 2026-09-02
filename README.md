# Auditoria de Empenho, Liquidação e Pagamento

App Streamlit para análise dos CSVs exportados do SCP-550.

## Como rodar

```powershell
venv\Scripts\activate
streamlit run app.py
```

## Estrutura

- `app.py` — navegação (st.navigation) entre as páginas.
- `pages/00_fonte_dados.py` — status dos CSVs em `data/scp550/`, recarga do cache, amostra e qualidade dos dados.
- `pages/01_empenho.py`, `02_liquidacao.py`, `03_pagamento.py` — filtros, KPIs, gráficos e pontos de atenção de auditoria.
- `pages/04_extrato_apmif.py`, `04_extrato_182001.py` — extratos bancários por conta (`data/extratos/`).
- `utils/dados.py` — leitura tolerante dos CSVs (Latin-1, `;`, datas `dd.mm.aaaa`, inteiros com ponto de milhar,
  negativos entre parênteses, `;` dentro de DESCRICAO) e utilitários compartilhados.

## Dados

Coloque em `data/scp550/` os arquivos `Empenhos2013a2026.csv`, `Liquidacoes2013a2026.csv` e `Pagamentos2013a2026.csv`.
O cache é invalidado automaticamente quando a data de modificação de um arquivo muda.
