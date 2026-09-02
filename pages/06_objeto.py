"""Custos por objeto da despesa, cruzando natureza x categoria x secretaria."""
import altair as alt
import pandas as pd
import streamlit as st

from utils import dados

st.title("🔖 Custos por objeto")
st.caption(
    "A base do SCP-550 não tem campo de objeto. Esta página cruza a **natureza da despesa** "
    "(classificação oficial, sempre preenchida) com uma **categoria de objeto** deduzida por "
    "palavra-chave do texto do empenho, separadas por secretaria."
)

emp = dados.empenhos_por_objeto(dados.mtime_de("empenhos"))
emp = emp[~emp["ESTORNO"]]

# ---------------------------------------------------------------- filtros
st.sidebar.header("Filtros", help="Cumulativos; valem para os indicadores, as tabelas, o gráfico e os CSVs exportados.")
anos = sorted(emp["ANO"].dropna().unique().tolist())
sel_anos = st.sidebar.multiselect("Exercício", anos, default=anos[-3:], key="obj_ano",
                                  help="Vazio = todos os exercícios da base.")
sel_sec = st.sidebar.multiselect("Secretaria", sorted(emp["SECRETARIA"].dropna().unique()), key="obj_sec",
                                 help="Órgão orçamentário (os 2 primeiros dígitos da unidade). Vazio = todas.")
sel_obj = st.sidebar.multiselect("Objeto", sorted(emp["OBJETO"].dropna().unique()), key="obj_obj",
                                 help="Categoria deduzida do texto do empenho. Vazio = todas.")
sel_nat = st.sidebar.multiselect("Natureza", sorted(emp["NATUREZA"].dropna().unique()), key="obj_nat",
                                 help="Natureza da despesa do SCP-550. Vazio = todas.")
busca = st.sidebar.text_input("Descrição contém", key="obj_busca",
                              help="Busca sem diferenciar maiúsculas. Os acentos vieram como '.' na base "
                                   "(AQUISI..O), então prefira palavras sem acento.")

df = emp
if sel_anos:
    df = df[df["ANO"].isin(sel_anos)]
for col, sel in [("SECRETARIA", sel_sec), ("OBJETO", sel_obj), ("NATUREZA", sel_nat)]:
    if sel:
        df = df[df[col].isin(sel)]
if busca:
    df = df[df["DESCRICAO"].str.contains(busca, case=False, na=False, regex=False)]

if df.empty:
    st.warning("Nenhum empenho para os filtros selecionados.")
    st.stop()

# ---------------------------------------------------------------- KPIs
total = df["VALOR"].sum()
classificado = df.loc[df["OBJETO"] != dados.SEM_CATEGORIA, "VALOR"].sum()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Empenhado", dados.brl(total))
k2.metric("Empenhos", f"{len(df):,}".replace(",", "."))
k3.metric("Objeto identificado", f"{100 * classificado / total:.0f}%" if total else "—",
          help=f"Parcela do valor que caiu numa categoria; o resto ficou em '{dados.SEM_CATEGORIA}'.")
k4.metric("Com quantidade", f"{100 * df['QUANTIDADE'].notna().mean():.0f}%",
          help="Empenhos cuja descrição permitiu extrair a quantidade comprada.")

st.warning(
    f"**Leia antes de usar os números.** A categoria de objeto é deduzida por palavra-chave e "
    f"{100 * (1 - classificado / total):.0f}% do valor não casou com nenhuma regra (fica em "
    f"*{dados.SEM_CATEGORIA}*). Além disso, {100 * df['DESCRICAO_TRUNCADA'].mean():.0f}% das descrições "
    "estão cortadas em 150 caracteres na exportação do SCP-550, então parte do objeto simplesmente não "
    "está no dado. **A natureza da despesa é a classificação confiável**; a categoria serve para navegar.",
    icon="⚠️",
)

cobertura_qtd = df["QUANTIDADE"].notna().mean()
if cobertura_qtd < 0.02:
    st.error(
        f"**Quantidade praticamente indisponível neste filtro** ({100 * cobertura_qtd:.1f}% dos empenhos). "
        "A quantidade só existe quando quem digitou o empenho a escreveu no texto, e esse hábito se perdeu: "
        "a cobertura cai de 12% em 2015 para perto de zero a partir de 2024. Para trabalhar com quantidade, "
        "filtre os exercícios até 2019 — e ainda assim ela cobre menos de 10% dos empenhos.",
        icon="🚫",
    )

aba_sec, aba_obj, aba_det, aba_emp = st.tabs(
    ["🏛️ Secretaria × objeto", "📦 Por objeto", "🧾 Natureza × objeto × secretaria", "📄 Empenhos"]
)


def _agrupar(chaves: list[str]) -> pd.DataFrame:
    g = df.groupby(chaves, dropna=False).agg(
        Valor=("VALOR", "sum"), Empenhos=("EMPENHO", "nunique"),
        Fornecedores=("FORNECEDOR_COD", "nunique"),
        Quantidade=("QUANTIDADE", "sum"), Com_qtd=("QUANTIDADE", "count"),
    ).reset_index()
    # Só faz sentido somar quantidade quando a unidade de medida é uma só.
    un = df.dropna(subset=["QUANTIDADE"]).groupby(chaves, dropna=False)["UN_MEDIDA"].agg(
        lambda s: s.iloc[0] if s.nunique() == 1 else "misto"
    )
    g = g.join(un.rename("Unidade"), on=chaves)
    g.loc[g["Unidade"].isna() | (g["Unidade"] == "misto"), "Quantidade"] = pd.NA
    g["% do valor"] = (100 * g["Valor"] / total).round(2)
    return g.sort_values("Valor", ascending=False)


CFG = {
    "Valor": st.column_config.NumberColumn("Valor (R$)", format="%.2f"),
    "Quantidade": st.column_config.NumberColumn(
        "Qtd. itens", format="%.2f",
        help="Soma das quantidades extraídas do texto. Fica vazia quando o grupo mistura unidades de medida "
             "(não dá para somar litros com quilos) ou quando nenhuma descrição do grupo trazia quantidade.",
    ),
    "Com_qtd": st.column_config.NumberColumn("Empenhos c/ qtd", help="Quantos empenhos do grupo tinham quantidade no texto."),
    "Unidade": st.column_config.TextColumn("Un.", help="Unidade de medida da quantidade somada."),
}

with aba_sec:
    st.caption("Uma linha por secretaria e objeto, do maior gasto para o menor.")
    t = _agrupar(["SECRETARIA", "OBJETO"])
    dados.tabela(t, hide_index=True, column_config=CFG)
    st.download_button("⬇️ Baixar CSV", dados.df_para_csv(t), "custos_secretaria_objeto.csv", "text/csv", key="dl_obj_1")

    st.subheader("Matriz de valor")
    st.caption("Total empenhado por secretaria (linhas) e objeto (colunas).")
    pv = t.pivot_table(index="SECRETARIA", columns="OBJETO", values="Valor", aggfunc="sum", fill_value=0)
    pv["TOTAL"] = pv.sum(axis=1)
    st.dataframe(pv.sort_values("TOTAL", ascending=False).round(2), width="stretch")

with aba_obj:
    t = _agrupar(["OBJETO"])
    dados.tabela(t, hide_index=True, column_config=CFG)
    st.download_button("⬇️ Baixar CSV", dados.df_para_csv(t), "custos_por_objeto.csv", "text/csv", key="dl_obj_2")

with aba_det:
    st.caption("Natureza da despesa como nível principal e a categoria de objeto dentro dela.")
    t = _agrupar(["NATUREZA", "OBJETO", "SECRETARIA"])
    dados.tabela(t, hide_index=True, column_config=CFG)
    st.download_button("⬇️ Baixar CSV", dados.df_para_csv(t), "custos_natureza_objeto.csv", "text/csv", key="dl_obj_3")

with aba_emp:
    COLS = ["DATA", "EMPENHO", "SECRETARIA", "OBJETO", "NATUREZA", "FORNECEDOR_NOME",
            "VALOR", "QUANTIDADE", "UN_MEDIDA", "DESCRICAO_TRUNCADA", "DESCRICAO"]
    dados.tabela(
        df[COLS].sort_values("VALOR", ascending=False), hide_index=True,
        column_config={**CFG, "DESCRICAO_TRUNCADA": st.column_config.CheckboxColumn(
            "Cortada?", disabled=True, help="A descrição bateu no limite de 150 caracteres da exportação.")},
    )
    st.download_button("⬇️ Baixar CSV", dados.df_para_csv(df[COLS]), "empenhos_por_objeto.csv", "text/csv", key="dl_obj_4")

# ---------------------------------------------------------------- gráfico
st.subheader("Maiores objetos por secretaria")
st.caption("15 maiores categorias de objeto no filtro atual, empilhadas pela secretaria que gastou.")
top = _agrupar(["OBJETO"]).head(15)["OBJETO"].tolist()
g = (
    df[df["OBJETO"].isin(top)].groupby(["OBJETO", "SECRETARIA"], as_index=False)["VALOR"].sum()
    .rename(columns={"OBJETO": "Objeto", "SECRETARIA": "Secretaria", "VALOR": "Valor"})
)
st.altair_chart(
    alt.Chart(g).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4).encode(
        y=alt.Y("Objeto:N", sort=top, title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X("Valor:Q", title="R$ empenhado", axis=alt.Axis(format="~s")),
        color=alt.Color("Secretaria:N", legend=alt.Legend(title=None, orient="bottom", columns=2),
                        scale=alt.Scale(scheme="tableau20")),
        tooltip=[alt.Tooltip("Objeto:N"), alt.Tooltip("Secretaria:N"),
                 alt.Tooltip("Valor:Q", title="Valor (R$)", format=",.2f")],
    ).properties(height=520),
    use_container_width=True,
)
