import streamlit as st

st.set_page_config(
    page_title="Auditoria de Empenho, Liquidação e Pagamento",
    page_icon="🧾",
    layout="wide",
)

pages = {
    "➡️ SCP-550": [
        st.Page("pages/00_fonte_dados.py", title="Fonte de Dados"),
        st.Page("pages/01_empenho.py", title="Empenho"),
        st.Page("pages/02_liquidacao.py", title="Liquidação"),
        st.Page("pages/03_pagamento.py", title="Pagamento"),
        # st.Page("pages/06_objeto.py", title="Custos por objeto"),
        st.Page("pages/05_irregularidades.py", title="Possíveis irregularidades SCP-550"),
    ],

    "➡️ Bancos": [
        # st.Page("pages/04_extrato_182001.py", title="Extrato 18.200-1"),
        st.Page("pages/04_extrato_apmif.py", title="Extrato APMIF"),
    ],
}

pg = st.navigation(pages)
pg.run()
