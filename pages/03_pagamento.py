import streamlit as st

from utils import dados

st.title("💸 Pagamentos")

df_full = dados.exigir_base("pagamentos")
df = dados.filtro_padrao(df_full, "pag")

if df.empty:
    st.warning("Nenhum registro para os filtros selecionados.")
    st.stop()

efetivos = df[~df["ESTORNO"]]
estornos = df[df["ESTORNO"]]

# ---------------------------------------------------------------- KPIs
dados.kpis_valor(df, "VALOR_PAGO", "Pago")
c1, c2 = st.columns(2)
c1.metric("Retenções (líquido de estornos)", dados.brl(df["RETENCOES"].sum()))
c2.metric("Pago líquido após retenções", dados.brl(df["LIQUIDO"].sum()))

# ---------------------------------------------------------------- gráficos
aba_mes, aba_forn, aba_fonte = st.tabs(["Por mês", "Por fornecedor", "Por fonte"])
with aba_mes:
    st.bar_chart(efetivos.groupby("MES")["VALOR_PAGO"].sum().sort_index())
with aba_forn:
    st.bar_chart(efetivos.groupby("FORNECEDOR_NOME")["VALOR_PAGO"].sum().sort_values(ascending=False).head(20), horizontal=True)
with aba_fonte:
    st.bar_chart(efetivos.groupby("FONTE")["VALOR_PAGO"].sum().sort_values(ascending=False), horizontal=True)

# ---------------------------------------------------------------- auditoria
st.subheader("Pontos de atenção")
liq = dados.exigir_base("liquidacoes")
liq_por_liq = liq.groupby("LIQUIDACAO")["VALOR"].sum()

a1, a2, a3 = st.tabs(["Pago acima do liquidado", "Sem liquidação correspondente", "Estornos"])
with a1:
    pago = df.groupby("LIQUIDACAO").agg(  # soma líquida de estornos
        DATA=("DATA", "min"), EMPENHO=("EMPENHO", "first"),
        FORNECEDOR_NOME=("FORNECEDOR_NOME", "first"), PAGO=("VALOR_PAGO", "sum"),
    )
    pago["LIQUIDADO"] = liq_por_liq.reindex(pago.index)
    acima = pago[pago["LIQUIDADO"].notna() & (pago["PAGO"] - pago["LIQUIDADO"] > 0.005)]
    acima = acima.assign(DIFERENCA=acima["PAGO"] - acima["LIQUIDADO"]).sort_values("DIFERENCA", ascending=False)
    st.write(f"{len(acima)} liquidação(ões) com pagamento superior ao valor liquidado.")
    dados.tabela(acima)
with a2:
    sem = efetivos[~efetivos["LIQUIDACAO"].isin(set(liq["LIQUIDACAO"].dropna()))]
    st.write(f"{len(sem)} pagamento(s) cuja liquidação não consta na base "
             "(pode ser restos a pagar de exercício anterior).")
    dados.tabela(sem, hide_index=True)
with a3:
    st.write(f"{len(estornos)} estorno(s).")
    dados.tabela(estornos, hide_index=True)

# ---------------------------------------------------------------- tabela
st.subheader("Registros")
dados.tabela(df, hide_index=True)
st.download_button(
    "⬇️ Baixar CSV filtrado",
    df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    "pagamentos_filtrado.csv",
    "text/csv",
)
