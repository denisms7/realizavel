"""Testes de auditoria cruzando Empenhos x Liquidações x Pagamentos."""
import pandas as pd
import streamlit as st

from utils import dados

st.title("🚩 Possíveis irregularidades")
st.caption(
    "Testes automáticos sobre as três bases do SCP-550. Cada apontamento é um **indício** que "
    "precisa ser confirmado nos documentos do processo — não uma conclusão de irregularidade."
)

emp = dados.exigir_base("empenhos")
liq = dados.exigir_base("liquidacoes")
pag = dados.exigir_base("pagamentos")

# ---------------------------------------------------------------- parâmetros
st.sidebar.header("Parâmetros")
anos = sorted(set(emp["ANO"].dropna()) | set(liq["ANO"].dropna()) | set(pag["ANO"].dropna()))
sel_anos = st.sidebar.multiselect("Exercício(s) analisado(s)", anos, default=anos[-1:], key="irr_anos")
limite_frac = st.sidebar.number_input(
    "Limite de dispensa para fracionamento (R$)", min_value=1000.0, value=59906.02, step=1000.0,
    help="Soma anual de empenhos SEM modalidade de licitação, por fornecedor e natureza, acima da qual há indício de fracionamento.",
)
tolerancia = st.sidebar.number_input("Tolerância de valor (R$)", min_value=0.0, value=0.01, step=0.01)
dias_pagto = st.sidebar.number_input("Pagamento em menos de (dias) após a liquidação", min_value=0, value=0,
                                     help="0 = aponta apenas pagamento anterior à liquidação.")

if not sel_anos:
    st.warning("Selecione ao menos um exercício.")
    st.stop()

e = emp[emp["ANO"].isin(sel_anos)]
l = liq[liq["ANO"].isin(sel_anos)]
p = pag[pag["ANO"].isin(sel_anos)]
en, ln, pn = e[~e["ESTORNO"]], l[~l["ESTORNO"]], p[~p["ESTORNO"]]

# Totais líquidos por chave (considerando estornos), usando as bases COMPLETAS
# para não perder empenhos/liquidações de exercícios anteriores (restos a pagar).
emp_liq_por_emp = emp.groupby("EMPENHO")["VALOR"].sum()
liq_liq_por_emp = liq.groupby("EMPENHO")["VALOR"].sum()
liq_liq_por_liq = liq.groupby("LIQUIDACAO")["VALOR"].sum()
pag_liq_por_liq = pag.groupby("LIQUIDACAO")["VALOR_PAGO"].sum()
data_emp = emp[~emp["ESTORNO"]].groupby("EMPENHO")["DATA"].min()
data_liq = liq[~liq["ESTORNO"]].groupby("LIQUIDACAO")["DATA"].min()
info_emp = emp[~emp["ESTORNO"]].drop_duplicates("EMPENHO").set_index("EMPENHO")[["DATA", "FORNECEDOR_NOME", "NATUREZA", "UNIDADE", "DESCRICAO"]]

testes: list[tuple[str, str, pd.DataFrame, str]] = []  # (título, gravidade, tabela, explicação)

# 1. Pagamento sem liquidação ---------------------------------------------------
t = pn[~pn["LIQUIDACAO"].isin(liq["LIQUIDACAO"])]
testes.append((
    "Pagamento sem liquidação correspondente", "alta",
    t[["DATA", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO", "RETENCOES", "LIQUIDO"]],
    "Pagamento cuja liquidação não existe em nenhuma base carregada. Viola a ordem empenho → liquidação → pagamento "
    "(art. 62 e 63 da Lei 4.320/64). Pode ser liquidação anterior a 2013.",
))

# 2. Liquidação sem empenho -----------------------------------------------------
t = ln[~ln["EMPENHO"].isin(emp["EMPENHO"])]
testes.append((
    "Liquidação sem empenho correspondente", "alta",
    t[["DATA", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR", "TIPO_DOCUMENTO", "DESCRICAO"]],
    "Liquidação referenciando empenho inexistente nas bases (art. 60 da Lei 4.320/64 veda despesa sem prévio empenho). "
    "Pode ser empenho anterior a 2013.",
))

# 3. Pago acima do liquidado ----------------------------------------------------
chaves = pn["LIQUIDACAO"].unique()
t = pd.DataFrame({"PAGO": pag_liq_por_liq.reindex(chaves), "LIQUIDADO": liq_liq_por_liq.reindex(chaves)}).dropna()
t["DIFERENCA"] = t["PAGO"] - t["LIQUIDADO"]
t = t[t["DIFERENCA"] > tolerancia].sort_values("DIFERENCA", ascending=False)
t = t.join(pn.drop_duplicates("LIQUIDACAO").set_index("LIQUIDACAO")[["EMPENHO", "FORNECEDOR_NOME"]]).reset_index(names="LIQUIDACAO")
testes.append((
    "Pagamento acumulado superior ao valor liquidado", "alta", t,
    "Soma dos pagamentos (líquida de estornos) maior que a soma das liquidações da mesma chave.",
))

# 4. Liquidado acima do empenhado -----------------------------------------------
chaves = ln["EMPENHO"].unique()
t = pd.DataFrame({"LIQUIDADO": liq_liq_por_emp.reindex(chaves), "EMPENHADO": emp_liq_por_emp.reindex(chaves)}).dropna()
t["DIFERENCA"] = t["LIQUIDADO"] - t["EMPENHADO"]
t = t[t["DIFERENCA"] > tolerancia].sort_values("DIFERENCA", ascending=False)
t = t.join(info_emp[["FORNECEDOR_NOME", "NATUREZA"]]).reset_index(names="EMPENHO")
testes.append((
    "Liquidação acumulada superior ao valor empenhado", "alta", t,
    "Soma das liquidações (líquida de estornos) maior que o saldo empenhado (empenho menos anulações). "
    "Indica despesa realizada sem cobertura de empenho ou reforço não registrado.",
))

# 5. Pagamento antes da liquidação ----------------------------------------------
t = pn.assign(DATA_LIQUIDACAO=pn["LIQUIDACAO"].map(data_liq))
t = t[t["DATA_LIQUIDACAO"].notna()]
t = t.assign(DIAS=(t["DATA"] - t["DATA_LIQUIDACAO"]).dt.days)
t = t[t["DIAS"] < dias_pagto if dias_pagto > 0 else t["DIAS"] < 0]
testes.append((
    "Pagamento anterior à data da liquidação", "alta",
    t[["DATA", "DATA_LIQUIDACAO", "DIAS", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO"]].sort_values("DIAS"),
    "A data do pagamento é anterior à data da liquidação a que se refere (art. 62 da Lei 4.320/64).",
))

# 6. Liquidação antes do empenho ------------------------------------------------
t = ln.assign(DATA_EMPENHO=ln["EMPENHO"].map(data_emp))
t = t[t["DATA_EMPENHO"].notna() & (t["DATA"] < t["DATA_EMPENHO"])]
testes.append((
    "Liquidação anterior à data do empenho", "alta",
    t[["DATA", "DATA_EMPENHO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR", "TIPO_DOCUMENTO"]],
    "A liquidação foi registrada antes do próprio empenho (art. 60 da Lei 4.320/64).",
))

# 7. Fracionamento de despesa ---------------------------------------------------
sem_lic = en[en["MODALIDADE"].fillna("") == ""]
g = sem_lic.groupby(["ANO", "FORNECEDOR_COD", "FORNECEDOR_NOME", "NATUREZA"], dropna=False).agg(
    EMPENHOS=("EMPENHO", "nunique"), VALOR=("VALOR", "sum"), PRIMEIRO=("DATA", "min"), ULTIMO=("DATA", "max"),
).reset_index()
t = g[(g["EMPENHOS"] >= 2) & (g["VALOR"] > limite_frac)].sort_values("VALOR", ascending=False)
testes.append((
    "Indício de fracionamento de despesa", "média", t,
    f"Mesmo fornecedor e mesma natureza de despesa, no mesmo exercício, com 2+ empenhos **sem modalidade de licitação** "
    f"somando mais de {dados.brl(limite_frac)}. Exclui empenhos com Pregão, Dispensa, Inexigibilidade etc. informados. "
    "Confirmar se houve processo licitatório ou hipótese legal de dispensa/inexigibilidade.",
))

# 8. Pagamentos possivelmente duplicados ----------------------------------------
ch = ["FORNECEDOR_COD", "DATA", "VALOR_PAGO"]
t = pn[pn["VALOR_PAGO"] > 0]
t = t[t.duplicated(ch, keep=False)]
t = t[t.groupby(ch)["LIQUIDACAO"].transform("nunique") > 1].sort_values(ch)
testes.append((
    "Pagamentos possivelmente duplicados", "média",
    t[["DATA", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO", "NATUREZA"]],
    "Mesmo fornecedor, mesma data e mesmo valor pagos em liquidações diferentes. Podem ser parcelas legítimas "
    "(ex.: folha, contratos com várias unidades) — verificar os documentos fiscais.",
))

# 9. Documento fiscal repetido --------------------------------------------------
ch = ["FORNECEDOR_COD", "TIPO_DOCUMENTO", "SERIE"]
t = ln[ln["TIPO_DOCUMENTO"].fillna("") != ""]
t = t[t.duplicated(ch, keep=False)]
t = t[t.groupby(ch)["LIQUIDACAO"].transform("nunique") > 1].sort_values(ch + ["DATA"])
testes.append((
    "Mesmo documento fiscal em liquidações distintas", "média",
    t[["DATA", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "TIPO_DOCUMENTO", "SERIE", "VALOR"]],
    "O mesmo número/série de documento do mesmo fornecedor aparece em mais de uma liquidação. Possível liquidação em duplicidade "
    "(ou nota liquidada em parcelas — verificar se a soma bate com o documento).",
))

# 10. Lançamentos em fim de semana ----------------------------------------------
fds = lambda df: df[df["DATA"].dt.dayofweek >= 5]
t = pd.concat([
    fds(en).assign(BASE="Empenho", CHAVE=lambda d: d["EMPENHO"], VALOR=lambda d: d["VALOR"]),
    fds(ln).assign(BASE="Liquidação", CHAVE=lambda d: d["LIQUIDACAO"], VALOR=lambda d: d["VALOR"]),
    fds(pn).assign(BASE="Pagamento", CHAVE=lambda d: d["PAGAMENTO"], VALOR=lambda d: d["VALOR_PAGO"]),
])
t = t.assign(DIA=t["DATA"].dt.dayofweek.map({5: "Sábado", 6: "Domingo"}))
testes.append((
    "Lançamentos em sábado ou domingo", "baixa",
    t[["BASE", "DATA", "DIA", "CHAVE", "EMPENHO", "FORNECEDOR_NOME", "VALOR"]].sort_values("DATA"),
    "Registros em dias sem expediente. Podem ser legítimos (folha, tarifas bancárias, retroação) mas merecem atenção.",
))

# 11. Empenhos no último dia do exercício -------------------------------------
t = en[(en["DATA"].dt.month == 12) & (en["DATA"].dt.day >= 30)]
testes.append((
    "Empenhos em 30 ou 31 de dezembro", "baixa",
    t[["DATA", "EMPENHO", "FORNECEDOR_NOME", "NATUREZA", "VALOR", "DESCRICAO"]].sort_values("VALOR", ascending=False),
    "Empenhos de fim de exercício podem indicar 'empenho de sobra de dotação' para inscrição em restos a pagar sem despesa efetiva.",
))

# 12. Empenho sem descrição -------------------------------------------------------
t = en[en["DESCRICAO"].fillna("").str.len() < 10]
testes.append((
    "Empenho sem descrição (ou descrição muito curta)", "baixa",
    t[["DATA", "EMPENHO", "FORNECEDOR_NOME", "NATUREZA", "VALOR", "DESCRICAO"]],
    "Histórico insuficiente dificulta a verificação do objeto da despesa.",
))

# 12b. Estornos superiores ao lançamento original --------------------------------
t_e = emp_liq_por_emp[emp_liq_por_emp < -tolerancia]
t_e = t_e[t_e.index.isin(e["EMPENHO"])].to_frame("SALDO").join(info_emp[["DATA", "FORNECEDOR_NOME"]]).reset_index(names="CHAVE").assign(BASE="Empenho")
t_l = liq_liq_por_liq[liq_liq_por_liq < -tolerancia]
t_l = t_l[t_l.index.isin(l["LIQUIDACAO"])].to_frame("SALDO").join(
    liq[~liq["ESTORNO"]].drop_duplicates("LIQUIDACAO").set_index("LIQUIDACAO")[["DATA", "FORNECEDOR_NOME"]]
).reset_index(names="CHAVE").assign(BASE="Liquidação")
t = pd.concat([t_e, t_l])[["BASE", "CHAVE", "DATA", "FORNECEDOR_NOME", "SALDO"]].sort_values("SALDO")
testes.append((
    "Estornos superiores ao lançamento original (saldo negativo)", "média", t,
    "A soma dos estornos de um empenho/liquidação excede o valor original. Frequentemente é o mesmo estorno "
    "exportado em duplicidade pelo SCP-550 (uma linha por documento fiscal), mas pode ser estorno indevido — conferir no sistema.",
))

# 13. Empenhos sem qualquer liquidação (saldo integral) -------------------------
saldo = emp_liq_por_emp.reindex(en["EMPENHO"].unique()).to_frame("EMPENHADO")
saldo["LIQUIDADO"] = liq_liq_por_emp.reindex(saldo.index).fillna(0)
t = saldo[(saldo["EMPENHADO"] > tolerancia) & (saldo["LIQUIDADO"] == 0)].join(info_emp).reset_index(names="EMPENHO")
testes.append((
    "Empenhos sem nenhuma liquidação", "info",
    t.sort_values("EMPENHADO", ascending=False),
    "Saldo empenhado integralmente sem liquidação. Normal no exercício corrente; em exercícios encerrados indica restos a pagar não processados.",
))

# 14. Concentração de fornecedores ----------------------------------------------
tot = pn["VALOR_PAGO"].sum()
t = pn.groupby(["FORNECEDOR_COD", "FORNECEDOR_NOME"]).agg(PAGAMENTOS=("PAGAMENTO", "nunique"), VALOR_PAGO=("VALOR_PAGO", "sum")).reset_index()
t["% DO TOTAL"] = (100 * t["VALOR_PAGO"] / tot).round(2) if tot else 0
t = t.sort_values("VALOR_PAGO", ascending=False).head(30)
testes.append((
    "Concentração de pagamentos por fornecedor (top 30)", "info", t,
    "Informativo: fornecedores que concentram a maior parte dos pagamentos do período.",
))

# ---------------------------------------------------------------- resumo
COR = {"alta": "🔴", "média": "🟠", "baixa": "🟡", "info": "🔵"}
resumo = pd.DataFrame(
    [{"Gravidade": f"{COR[g]} {g}", "Teste": titulo, "Apontamentos": len(t)} for titulo, g, t, _ in testes]
)
st.subheader("Resumo")
c1, c2, c3, c4 = st.columns(4)
for col, g in zip([c1, c2, c3, c4], ["alta", "média", "baixa", "info"]):
    n = sum(len(t) for _, gg, t, _ in testes if gg == g)
    col.metric(f"{COR[g]} Gravidade {g}", f"{n:,}".replace(",", "."))
st.dataframe(resumo, hide_index=True, width="stretch")

# ---------------------------------------------------------------- detalhes
st.subheader("Detalhamento")
so_com_apontamento = st.toggle("Mostrar apenas testes com apontamentos", value=True)
for i, (titulo, g, t, explicacao) in enumerate(testes):
    if so_com_apontamento and t.empty:
        continue
    with st.expander(f"{COR[g]} {titulo} — {len(t):,} apontamento(s)".replace(",", "."), expanded=False):
        dados.texto(explicacao)
        if t.empty:
            st.success("Nenhum apontamento para os exercícios selecionados.")
            continue
        dados.tabela(t, hide_index=True)
        st.download_button(
            "⬇️ Baixar CSV", t.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            f"irregularidade_{i + 1:02d}.csv", "text/csv", key=f"dl_irr_{i}",
        )
