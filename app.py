import streamlit as st

st.set_page_config(
    page_title="Auditoria de Empenho, Liquidação e Pagamento",
    page_icon="🧾",
    layout="wide",
)

pages = {
    "➡️ SCP": [
        st.Page("pages/01_empenho.py", title="Empenho"),
        st.Page("pages/02_liquidacao.py", title="Liquidação"),
        st.Page("pages/03_pagamento.py", title="Pagamento"),
    ],

    "➡️ Bancos": [
        st.Page("pages/04_extrato.py", title="Extrato"),
    ],

    "⚙️ Sistema": [
        st.Page("pages/00_fonte_dados.py", title="Fonte de Dados"),
    ],

}

pg = st.navigation(pages)
pg.run()
