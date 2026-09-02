import pandas as pd
import streamlit as st

from utils import dados

st.title("📝 Empenhos")

df_full = dados.exigir_base("empenhos")
df = dados.filtro_padrao(df_full, "emp")

if df.empty:
    st.warning("Nenhum registro para os filtros selecionados.")
    st.stop()

# ---------------------------------------------------------------- KPIs
positivos = df.loc[df["VALOR"] > 0, "VALOR"].sum()
anulacoes = -df.loc[df["VALOR"] < 0, "VALOR"].sum()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Registros", f"{len(df):,}".replace(",", "."))
c2.metric("Empenhado (bruto)", dados.brl(positivos))
c3.metric("Anulações", dados.brl(anulacoes))
c4.metric("Empenhado líquido", dados.brl(df["VALOR"].sum()))

# ---------------------------------------------------------------- gráficos
aba_mes, aba_forn, aba_nat = st.tabs(["Por mês", "Por fornecedor", "Por natureza"])
with aba_mes:
    por_mes = df.groupby("MES", dropna=True)["VALOR"].sum().sort_index()
    st.bar_chart(por_mes)
with aba_forn:
    top = df.groupby("FORNECEDOR_NOME")["VALOR"].sum().sort_values(ascending=False).head(20)
    st.bar_chart(top, horizontal=True)
with aba_nat:
    nat = df.groupby("NATUREZA")["VALOR"].sum().sort_values(ascending=False).head(20)
    st.bar_chart(nat, horizontal=True)

# ---------------------------------------------------------------- auditoria
st.subheader("Pontos de atenção")
liq = dados.exigir_base("liquidacoes")
liq_por_emp = liq.groupby("EMPENHO")["VALOR"].sum()
saldo = df.groupby("EMPENHO")["VALOR"].sum().to_frame("EMPENHADO")
saldo["LIQUIDADO"] = liq_por_emp.reindex(saldo.index).fillna(0)
saldo["SALDO"] = saldo["EMPENHADO"] - saldo["LIQUIDADO"]
saldo = saldo.join(
    df.drop_duplicates("EMPENHO").set_index("EMPENHO")[["DATA", "FORNECEDOR_NOME", "NATUREZA", "DESCRICAO"]]
)

a1, a2, a3 = st.tabs(["Liquidado acima do empenhado", "Empenhos sem liquidação", "Anulações"])
with a1:
    acima = saldo[saldo["SALDO"] < -0.005].sort_values("SALDO")
    st.write(f"{len(acima)} empenho(s) com liquidação superior ao valor empenhado.")
    st.dataframe(acima, width="stretch")
with a2:
    sem = saldo[(saldo["LIQUIDADO"] == 0) & (saldo["EMPENHADO"] > 0)].sort_values("EMPENHADO", ascending=False)
    st.write(f"{len(sem)} empenho(s) sem nenhuma liquidação — total {dados.brl(sem['EMPENHADO'].sum())}.")
    st.dataframe(sem, width="stretch")
with a3:
    neg = df[df["VALOR"] < 0].sort_values("VALOR")
    st.write(f"{len(neg)} lançamento(s) de anulação/estorno.")
    st.dataframe(neg, width="stretch")

# ---------------------------------------------------------------- tabela
st.subheader("Registros")
st.dataframe(df, width="stretch", hide_index=True)
st.download_button(
    "⬇️ Baixar CSV filtrado",
    df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    "empenhos_filtrado.csv",
    "text/csv",
)
