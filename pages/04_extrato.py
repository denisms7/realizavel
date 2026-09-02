import pandas as pd
import streamlit as st

from utils import dados

st.title("🏦 Extrato bancário")
st.caption(
    "Envie o extrato exportado do banco (CSV) para cruzar os lançamentos de débito com os pagamentos do SCP-550. "
    "Ainda não há extrato na pasta de dados, por isso a carga é feita por upload."
)

arquivo = st.file_uploader("Extrato (CSV)", type=["csv", "txt"])
if arquivo is None:
    st.info("Aguardando arquivo. Colunas esperadas: data, descrição/histórico e valor (débitos negativos ou coluna separada).")
    st.stop()

sep = st.radio("Separador", [";", ",", "\t"], horizontal=True, format_func=lambda s: {"\t": "Tab"}.get(s, s))
enc = st.radio("Codificação", ["latin-1", "utf-8"], horizontal=True)
bruto = pd.read_csv(arquivo, sep=sep, encoding=enc, dtype=str)
st.dataframe(bruto.head(20), width="stretch")

st.subheader("Mapeamento de colunas")
cols = list(bruto.columns)
c1, c2, c3 = st.columns(3)
col_data = c1.selectbox("Data", cols)
col_hist = c2.selectbox("Histórico", cols)
col_valor = c3.selectbox("Valor", cols)
fmt = st.text_input("Formato da data", "%d/%m/%Y")

ext = pd.DataFrame(
    {
        "DATA": pd.to_datetime(bruto[col_data], format=fmt, errors="coerce"),
        "HISTORICO": bruto[col_hist],
        "VALOR": pd.to_numeric(
            bruto[col_valor].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
            errors="coerce",
        ),
    }
)
debitos = ext[ext["VALOR"] < 0].assign(VALOR=lambda d: -d["VALOR"])
st.write(f"{len(ext)} lançamentos lidos; {len(debitos)} débitos, total {dados.brl(debitos['VALOR'].sum())}.")

# ---------------------------------------------------------------- conciliação
st.subheader("Conciliação com pagamentos (mesma data e valor)")
pag = dados.exigir_base("pagamentos")
pag = pag[~pag["ESTORNO"]][["DATA", "PAGAMENTO", "EMPENHO", "FORNECEDOR_NOME", "LIQUIDO"]].rename(columns={"LIQUIDO": "VALOR"})
pag["VALOR"] = pag["VALOR"].round(2)
debitos = debitos.assign(VALOR=debitos["VALOR"].round(2))

conc = debitos.merge(pag, on=["DATA", "VALOR"], how="left", indicator=True)
sem_par = conc[conc["_merge"] == "left_only"].drop(columns="_merge")
com_par = conc[conc["_merge"] == "both"].drop(columns="_merge")

k1, k2 = st.columns(2)
k1.metric("Débitos com pagamento correspondente", len(com_par))
k2.metric("Débitos sem pagamento correspondente", len(sem_par))

t1, t2 = st.tabs(["Sem correspondência", "Conciliados"])
with t1:
    st.dataframe(sem_par, width="stretch", hide_index=True)
with t2:
    st.dataframe(com_par, width="stretch", hide_index=True)
