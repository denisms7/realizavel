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
dados.kpis_valor(df, "VALOR", "Empenhado")

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

a1, a2, a3 = st.tabs(["Liquidado acima do empenhado", "Empenhos sem liquidação", "Estornos"])
with a1:
    acima = saldo[saldo["SALDO"] < -0.005].sort_values("SALDO")
    st.write(f"{len(acima)} empenho(s) com liquidação superior ao valor empenhado.")
    dados.tabela(acima)
with a2:
    sem = saldo[(saldo["LIQUIDADO"] == 0) & (saldo["EMPENHADO"] > 0)].sort_values("EMPENHADO", ascending=False)
    dados.texto(f"{len(sem)} empenho(s) sem nenhuma liquidação — total {dados.brl(sem['EMPENHADO'].sum())}.")
    dados.tabela(sem)
with a3:
    est = df[df["ESTORNO"]].sort_values("VALOR")
    dados.texto(f"{len(est)} estorno(s)/anulação(ões) de empenho — total {dados.brl(-est['VALOR'].sum())}.")
    dados.tabela(est, hide_index=True)

# ---------------------------------------------------------------- tabela
st.subheader("Registros")
dados.tabela(df, hide_index=True)
st.download_button(
    "⬇️ Baixar CSV filtrado",
    df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    "empenhos_filtrado.csv",
    "text/csv",
)
