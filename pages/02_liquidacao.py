import streamlit as st

from utils import dados

st.title("✅ Liquidações")

df_full = dados.exigir_base("liquidacoes")
df = dados.filtro_padrao(df_full, "liq")

if df.empty:
    st.warning("Nenhum registro para os filtros selecionados.")
    st.stop()

# ---------------------------------------------------------------- KPIs
dados.kpis_valor(df, "VALOR", "Liquidado")
st.caption(
    f"{df['EMPENHO'].nunique():,} empenho(s) e {df['FORNECEDOR_NOME'].nunique():,} fornecedor(es) distintos.".replace(",", ".")
)

# ---------------------------------------------------------------- gráficos
aba_mes, aba_forn, aba_doc = st.tabs(["Por mês", "Por fornecedor", "Por tipo de documento"])
with aba_mes:
    st.bar_chart(df.groupby("MES")["VALOR"].sum().sort_index())
with aba_forn:
    st.bar_chart(df.groupby("FORNECEDOR_NOME")["VALOR"].sum().sort_values(ascending=False).head(20), horizontal=True)
with aba_doc:
    tipo_doc = df["TIPO_DOCUMENTO"].str.replace(r"\s*N[ºo°]?:.*$", "", regex=True).str.strip()
    st.bar_chart(df.assign(TIPO_DOC=tipo_doc).groupby("TIPO_DOC")["VALOR"].sum().sort_values(ascending=False).head(20), horizontal=True)

# ---------------------------------------------------------------- auditoria
st.subheader("Pontos de atenção")
emp = dados.exigir_base("empenhos")
pag = dados.exigir_base("pagamentos")
empenhos_existentes = set(emp["EMPENHO"].dropna())
pago_por_liq = pag[~pag["ESTORNO"]].groupby("LIQUIDACAO")["VALOR_PAGO"].sum()

a1, a2, a3, a4 = st.tabs(["Sem empenho correspondente", "Liquidado sem pagamento", "Documento fiscal duplicado", "Estornos"])
with a1:
    sem_emp = df[~df["EMPENHO"].isin(empenhos_existentes)]
    st.write(f"{len(sem_emp)} liquidação(ões) cujo empenho não consta na base de empenhos "
             "(pode ser empenho de exercício anterior / restos a pagar).")
    dados.tabela(sem_emp, hide_index=True)
with a2:
    resumo = df.groupby("LIQUIDACAO").agg(
        DATA=("DATA", "min"), FORNECEDOR_NOME=("FORNECEDOR_NOME", "first"),
        EMPENHO=("EMPENHO", "first"), LIQUIDADO=("VALOR", "sum"),
    )
    resumo["PAGO"] = pago_por_liq.reindex(resumo.index).fillna(0)
    resumo["A_PAGAR"] = resumo["LIQUIDADO"] - resumo["PAGO"]
    pend = resumo[resumo["A_PAGAR"] > 0.005].sort_values("A_PAGAR", ascending=False)
    st.write(f"{len(pend)} liquidação(ões) com saldo a pagar — total {dados.brl(pend['A_PAGAR'].sum())}.")
    dados.tabela(pend)
with a3:
    chave = ["FORNECEDOR_COD", "TIPO_DOCUMENTO", "SERIE"]
    dup = df[~df["ESTORNO"] & df["TIPO_DOCUMENTO"].notna() & (df["TIPO_DOCUMENTO"] != "")]
    dup = dup[dup.duplicated(chave, keep=False)].sort_values(chave + ["DATA"])
    st.write(f"{len(dup)} linha(s) com o mesmo fornecedor + documento + série, em liquidações diferentes.")
    dados.tabela(dup[["DATA", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "TIPO_DOCUMENTO", "SERIE", "VALOR", "DESCRICAO"]], hide_index=True)

with a4:
    est = df[df["ESTORNO"]].sort_values("VALOR")
    st.write(f"{len(est)} estorno(s) de liquidação — total {dados.brl(-est['VALOR'].sum())}.")
    dados.tabela(est, hide_index=True)

# ---------------------------------------------------------------- tabela
st.subheader("Registros")
dados.tabela(df, hide_index=True)
st.download_button(
    "⬇️ Baixar CSV filtrado",
    df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
    "liquidacoes_filtrado.csv",
    "text/csv",
)
