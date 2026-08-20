"""
Painel de Despesas - Prefeitura de Centenário do Sul
======================================================
Ponto de entrada do app. Define a navegação entre as páginas do ciclo da
despesa pública (empenhado, liquidado, pago) e a página de fontes de dados.

Como rodar:
    pip install -r requirements.txt
    streamlit run app.py

Estrutura de pastas:
    realizavel/
      app.py                                  <- ponto de entrada (este arquivo)
      pages/liquidado_x_pago.py               <- Liquidado x Pago
      pages/empenhado_liquidado_pago.py       <- Empenhado x Liquidado x Pago
      pages/fonte_de_dados.py                 <- Fonte de Dados (PDFs + CSVs)
      data/                                    <- os CSVs
      pdf/                                     <- os PDFs originais
"""

import streamlit as st

st.set_page_config(
    page_title="Despesas - Centenário do Sul",
    page_icon="🧾",
    layout="wide",
)

pages = {
    "➡️ Despesas": [
        st.Page("pages/liquidado_x_pago.py", title="Liquidado x Pago"),
        # st.Page("pages/empenhado_liquidado_pago.py", title="Empenhado x Liquidado x Pago"),
        st.Page("pages/fonte_de_dados.py", title="Fonte de Dados"),
    ],
}

pg = st.navigation(pages)
pg.run()
