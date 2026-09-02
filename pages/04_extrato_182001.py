"""Extrato da conta 18.200-1: leitura, downloads e cruzamento com o SCP-550."""
import altair as alt
import pandas as pd
import streamlit as st

from utils import dados

CSV = "Extrato_18.200-1.csv"
PDF = "Extrato_18.200-1.pdf"

st.title("🏦 Extrato bancário 18.200-1")
st.caption(
    "O extrato **não** traz empenho, liquidação nem conta de dotação, "
    "então o cruzamento com o SCP-550 é feito por **valor + proximidade de data** — é uma pista, não uma identificação."
)

ext = dados.exigir_extrato(CSV)
pag = dados.exigir_base("pagamentos")
emp = dados.exigir_base("empenhos")
liq = dados.exigir_base("liquidacoes")

# ---------------------------------------------------------------- downloads
c1, c2, _ = st.columns([1, 1, 3])
c1.download_button("⬇️ Extrato em PDF", dados.bytes_extrato(PDF), PDF, "application/pdf")
c2.download_button("⬇️ Extrato em CSV", dados.bytes_extrato(CSV), CSV, "text/csv")

# ---------------------------------------------------------------- filtros
st.sidebar.header("Filtros", help="Valem para os indicadores, para a tabela de lançamentos e para a conciliação.")
anos = sorted(ext["ANO"].dropna().unique().tolist())
sel_anos = st.sidebar.multiselect(
    "Ano", anos, default=anos, key="ex182_ano",
    help="Ano da data contábil do lançamento. Vazio = todos.",
)
mostrar_interno = st.sidebar.toggle(
    "Mostrar movimentação da aplicação", value=False, key="ex182_interno",
    help="Aplicações e resgates automáticos (`BB CP`, `APLIC`, `Resgate`) apenas movimentam dinheiro entre a conta "
         "corrente e a aplicação da própria conta. Não são despesa e nunca terão empenho — por isso ficam fora "
         "da conciliação, com ou sem este filtro.",
)
janela = st.sidebar.number_input(
    "Janela de conciliação (dias)", min_value=0, max_value=60, value=5, key="ex182_janela",
    help="Diferença máxima aceita entre a data do lançamento no banco e a data do pagamento no SCP-550. "
         "O cheque costuma compensar dias depois de emitido, por isso a janela olha para os dois lados.",
)

e = ext[ext["ANO"].isin(sel_anos)] if sel_anos else ext
visivel = e if mostrar_interno else e[~e["INTERNO"]]

# ---------------------------------------------------------------- KPIs
creditos = visivel.loc[visivel["TIPO"] == "C", "VALOR"].sum()
debitos = visivel.loc[visivel["TIPO"] == "D", "VALOR"].sum()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Lançamentos", f"{len(visivel):,}".replace(",", "."),
          help=f"Período de {e['DATA'].min():%d/%m/%Y} a {e['DATA'].max():%d/%m/%Y}." if len(e) else None)
k2.metric("Créditos", dados.brl(creditos))
k3.metric("Débitos", dados.brl(debitos))
k4.metric("Resultado", dados.brl(creditos - debitos))

aba_lanc, aba_conc, aba_hist = st.tabs(["📄 Lançamentos", "🔗 Conciliação com o SCP-550", "📊 Por histórico"])

# ---------------------------------------------------------------- lançamentos
with aba_lanc:
    COLS = ["DATA", "MOVIMENTO", "VALOR", "Historico", "Detalhe", "Documento", "CHEQUE", "INTERNO", "Folha"]
    dados.tabela(
        visivel[COLS].sort_values("DATA"), hide_index=True,
        column_config={
            "CHEQUE": st.column_config.CheckboxColumn("Cheque", disabled=True),
            "INTERNO": st.column_config.CheckboxColumn("Aplicação", disabled=True,
                                                       help="Movimentação interna da aplicação financeira."),
        },
    )
    st.download_button(
        "⬇️ Baixar lançamentos (CSV)", dados.df_para_csv(visivel[COLS]),
        "extrato_18200-1_lancamentos.csv", "text/csv", key="dl_ex182_lanc",
    )

# ---------------------------------------------------------------- conciliação
with aba_conc:
    dados.texto(
        "Cada **débito de despesa** do extrato é comparado aos pagamentos do SCP-550 (todas as bases, todos os anos) "
        "de mesmo valor — bruto ou líquido de retenções — dentro da janela de dias escolhida na barra lateral. "
        "Do candidato mais próximo vêm o pagamento, a liquidação e o empenho."
    )
    st.info(
        "**Como ler a coluna Confiança.** Não existe chave comum entre o extrato e o SCP-550. Quando o valor é redondo "
        "(R\$ 500,00, R\$ 2.000,00) dezenas de pagamentos diferentes casam com o mesmo débito, e a conciliação não "
        "identifica qual é. **Única** = só um pagamento compatível na janela, indício forte. **Ambígua (N)** = há N "
        "pagamentos igualmente compatíveis — serve para dizer que a despesa *poderia* existir, não qual foi.",
        icon="⚠️",
    )

    debitos_despesa = visivel[(visivel["TIPO"] == "D") & (~visivel["INTERNO"])]
    if debitos_despesa.empty:
        st.warning("Nenhum débito de despesa no período selecionado.")
        st.stop()

    conc = dados.conciliar_com_pagamentos(debitos_despesa, pag, janela=int(janela))
    conc["TEM_EMPENHO"] = conc["PAG_EMPENHO"].isin(emp["EMPENHO"])
    conc["TEM_LIQUIDACAO"] = conc["PAG_LIQUIDACAO"].isin(liq["LIQUIDACAO"])

    conciliados = conc["STATUS"].str.startswith("Conciliado")
    unicos = conciliados & (conc["CONFIANCA"] == "Única")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Débitos analisados", f"{len(conc):,}".replace(",", "."))
    m2.metric("Conciliados", f"{int(conciliados.sum()):,}".replace(",", "."),
              f"{100 * conciliados.mean():.0f}% do total", delta_color="off")
    m3.metric("Conciliação única", f"{int(unicos.sum()):,}".replace(",", "."),
              help="Um único pagamento compatível na janela — o indício mais forte.")
    m4.metric("Sem pagamento do valor", f"{int((conc['CANDIDATOS'] == 0).sum()):,}".replace(",", "."),
              help="Nenhum pagamento com esse valor em nenhum ano da base.")

    resumo = (
        conc.groupby("STATUS", dropna=False)
        .agg(Lançamentos=("VALOR", "size"), Valor=("VALOR", "sum"))
        .reset_index().sort_values("Lançamentos", ascending=False)
    )
    resumo["Valor"] = resumo["Valor"].map(dados.brl)
    st.dataframe(resumo, hide_index=True, width="stretch")

    st.subheader("Detalhamento")
    f1, f2 = st.columns(2)
    sel_status = f1.multiselect("Situação", sorted(conc["STATUS"].dropna().unique()), key="ex182_status")
    so_unicos = f2.toggle("Apenas conciliações únicas", value=False, key="ex182_unicos",
                          help="Esconde os casos em que vários pagamentos de mesmo valor cabem na janela.")
    t = conc
    if sel_status:
        t = t[t["STATUS"].isin(sel_status)]
    if so_unicos:
        t = t[t["CONFIANCA"] == "Única"]

    COLS_C = [
        "DATA", "VALOR", "Historico", "Documento", "CHEQUE", "STATUS", "CONFIANCA", "DIAS",
        "PAG_DATA", "PAG_PAGAMENTO", "PAG_LIQUIDACAO", "PAG_EMPENHO", "PAG_FORNECEDOR_NOME",
        "TEM_EMPENHO", "TEM_LIQUIDACAO", "CANDIDATOS_NA_JANELA", "CANDIDATOS",
    ]
    dados.tabela(
        t[COLS_C].sort_values("DATA"), hide_index=True,
        column_config={
            "CHEQUE": st.column_config.CheckboxColumn("Cheque", disabled=True),
            "TEM_EMPENHO": st.column_config.CheckboxColumn("Empenho?", disabled=True,
                                                           help="O empenho do pagamento casado existe na base de Empenhos."),
            "TEM_LIQUIDACAO": st.column_config.CheckboxColumn("Liquidação?", disabled=True,
                                                              help="A liquidação do pagamento casado existe na base de Liquidações."),
            "DIAS": st.column_config.NumberColumn("Dias", help="Data no banco menos data do pagamento. Negativo = pagamento posterior."),
            "CANDIDATOS": st.column_config.NumberColumn("Candidatos (base)", help="Pagamentos de mesmo valor em toda a base."),
            "CANDIDATOS_NA_JANELA": st.column_config.NumberColumn("Candidatos (janela)"),
        },
    )
    st.download_button(
        "⬇️ Baixar conciliação (CSV)", dados.df_para_csv(t[COLS_C]),
        "extrato_18200-1_conciliacao.csv", "text/csv", key="dl_ex182_conc",
    )

# ---------------------------------------------------------------- por histórico
with aba_hist:
    g = (
        visivel.groupby(["Historico", "MOVIMENTO"], dropna=False)
        .agg(Lançamentos=("VALOR", "size"), Valor=("VALOR", "sum"))
        .reset_index().sort_values("Valor", ascending=False)
    )
    dados.tabela(g, hide_index=True)

# ---------------------------------------------------------------- gráfico geral
st.subheader("Créditos e débitos")
st.caption(
    f"Extrato inteiro, de {ext['DATA'].min():%d/%m/%Y} a {ext['DATA'].max():%d/%m/%Y} — "
    "não segue os filtros da barra lateral e inclui a movimentação da aplicação financeira. "
    "O primeiro e o último período são parciais."
)

OPCOES = ["Mensal", "Anual"]
if hasattr(st, "pills"):  # st.pills existe a partir do Streamlit 1.40
    gran = st.pills("Agrupar por", options=OPCOES, default="Anual", key="ex182_gran")
else:
    gran = st.radio("Agrupar por", OPCOES, index=1, horizontal=True, key="ex182_gran")
gran = gran or "Anual"  # as pills permitem desmarcar a opção


def _rotulo(v: float) -> str:
    """Valor curto o bastante para caber sobre a barra."""
    if abs(v) >= 1_000_000:
        return dados.brl(round(v / 1_000_000, 2))[3:] + " mi"
    return dados.brl(round(v / 1_000))[3:].replace(",00", "") + " mil"


if gran == "Anual":
    base_df = ext.assign(Periodo=ext["ANO"].astype("Int64").astype(str))
else:
    # 'AAAA-MM' ordena sozinho; o rótulo exibido é 'MM/AAAA'.
    base_df = ext.assign(Periodo=ext["MES"])

serie = (
    base_df.groupby(["Periodo", "MOVIMENTO"], as_index=False)["VALOR"].sum()
    .rename(columns={"MOVIMENTO": "Movimento", "VALOR": "Valor"})
    .sort_values("Periodo")
)
ordem_x = serie["Periodo"].drop_duplicates().tolist()
if gran == "Mensal":
    serie["Rótulo_X"] = serie["Periodo"].str[5:7] + "/" + serie["Periodo"].str[:4]
else:
    serie["Rótulo_X"] = serie["Periodo"]
serie["Rótulo"] = serie["Valor"].map(_rotulo)

ORDEM = ["Crédito", "Débito"]
eixo_x = alt.Axis(labelAngle=0 if gran == "Anual" else -45, labelFontSize=12 if gran == "Anual" else 10,
                  labelOverlap="greedy", labelExpr="datum.label")
comum = dict(
    x=alt.X("Rótulo_X:O", title=None, sort=serie.drop_duplicates("Periodo")["Rótulo_X"].tolist(), axis=eixo_x),
    xOffset=alt.XOffset("Movimento:N", sort=ORDEM, scale=alt.Scale(paddingInner=0.12 if gran == "Anual" else 0)),
    y=alt.Y("Valor:Q", title="R$", axis=alt.Axis(format="~s", grid=True)),
)
base = alt.Chart(serie)
barras = base.mark_bar(cornerRadiusTopLeft=4 if gran == "Anual" else 2,
                       cornerRadiusTopRight=4 if gran == "Anual" else 2).encode(
    color=alt.Color(
        "Movimento:N", sort=ORDEM,
        scale=alt.Scale(domain=ORDEM, range=["#3B82F6", "#D97706"]),
        legend=alt.Legend(title=None, orient="top", direction="horizontal"),
    ),
    tooltip=[
        alt.Tooltip("Rótulo_X:O", title="Período"), alt.Tooltip("Movimento:N"),
        alt.Tooltip("Valor:Q", title="Valor (R$)", format=",.2f"),
    ],
    **comum,
)
grafico = barras
if gran == "Anual":
    # No mensal são ~50 períodos: um número sobre cada barra ficaria ilegível,
    # então o valor aparece só no tooltip.
    grafico = barras + base.mark_text(dy=-7, fontSize=11).encode(text=alt.Text("Rótulo:N"), **comum)
st.altair_chart(grafico.properties(height=340), use_container_width=True)

if gran == "Mensal":
    todos = pd.period_range(ext["DATA"].min(), ext["DATA"].max(), freq="M").astype(str)
    faltando = todos.difference(pd.Index(ordem_x))
    if len(faltando):
        st.caption(
            f"⚠️ O eixo traz apenas os {len(ordem_x)} meses com lançamento. O arquivo não cobre "
            f"{len(faltando)} mês(es) do período (ex.: {', '.join(faltando[:3])}), então meses "
            "distantes aparecem lado a lado — o eixo não é uma linha do tempo contínua."
        )
