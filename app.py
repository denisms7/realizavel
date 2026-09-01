import streamlit as st

st.set_page_config(
    page_title="Despesas - Centenário do Sul",
    page_icon="🧾",
    layout="wide",
)

pages = {
    "➡️ Realizável": [
        st.Page("pages/liquidado_x_pago.py", title="Liquidado x Pago"),
        st.Page("pages/00_fonte_dados.py", title="Fonte de Dados"),
    ],
}

pg = st.navigation(pages)
pg.run()
