"""Testes de auditoria cruzando Empenhos x Liquidações x Pagamentos."""
import inspect

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
st.sidebar.header("Parâmetros", help="Os parâmetros valem para todos os testes desta página. Os cruzamentos entre bases usam sempre as bases completas (todos os anos), para não perder empenhos/liquidações de exercícios anteriores.")
anos = sorted(set(emp["ANO"].dropna()) | set(liq["ANO"].dropna()) | set(pag["ANO"].dropna()))
sel_anos = st.sidebar.multiselect(
    "Exercício(s) analisado(s)", anos, default=anos[-1:], key="irr_anos",
    help="Restringe os lançamentos **analisados** (empenhos, liquidações e pagamentos com esse exercício na chave). "
         "As contrapartes usadas nos cruzamentos vêm de todos os anos — ex.: um pagamento de 2026 é comparado à sua liquidação mesmo que ela seja de 2025.",
)
limite_frac = st.sidebar.number_input(
    "Limite de dispensa para fracionamento (R$)", min_value=1000.0, value=59906.02, step=1000.0,
    help="Usado só no teste de fracionamento. Soma, por exercício + fornecedor + natureza, dos empenhos **sem** modalidade de licitação informada; "
         "quando há 2 ou mais empenhos e a soma passa deste valor, o grupo é apontado. "
         "Padrão: R$ 59.906,02 (limite de dispensa para compras/serviços, Lei 14.133/2021 atualizado). "
         "Para exercícios antigos sob a Lei 8.666/93 use R$ 17.600,00 (ou R$ 8.000,00 antes de 2018).",
)
tolerancia = st.sidebar.number_input(
    "Tolerância de valor (R$)", min_value=0.0, value=0.01, step=0.01,
    help="Diferença mínima para apontar 'pago acima do liquidado', 'liquidado acima do empenhado' e 'saldo negativo'. "
         "Evita apontamentos por arredondamento de centavos; aumente para ver só divergências relevantes.",
)
dias_pagto = st.sidebar.number_input(
    "Pagamento em menos de (dias) após a liquidação", min_value=0, value=0,
    help="Controla o teste 'pagamento anterior à liquidação'. Com **0**, aponta apenas pagamentos datados **antes** da liquidação. "
         "Com N > 0, aponta também pagamentos feitos em menos de N dias após a liquidação (útil para checar prazo mínimo de conferência).",
)

incluir_estornos = st.sidebar.toggle(
    "Considerar lançamentos de estorno", value=False,
    help="**Desligado** (padrão): os testes analisam apenas os lançamentos normais — estornos e anulações ficam de fora. "
         "**Ligado**: os estornos também entram nos testes e aparecem marcados na coluna **Estorno** de cada tabela. "
         "Os cruzamentos de valor (pago x liquidado x empenhado) usam totais líquidos e já consideram os estornos nos dois casos.",
)

if not sel_anos:
    st.warning("Selecione ao menos um exercício.")
    st.stop()

e = emp[emp["ANO"].isin(sel_anos)]
l = liq[liq["ANO"].isin(sel_anos)]
p = pag[pag["ANO"].isin(sel_anos)]
if incluir_estornos:
    en, ln, pn = e, l, p
else:
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

testes: list[tuple[str, str, pd.DataFrame, str, str]] = []  # (título, gravidade, tabela, explicação, método)

# 1. Pagamento sem liquidação ---------------------------------------------------
t = pn[~pn["LIQUIDACAO"].isin(liq["LIQUIDACAO"])]
testes.append((
    "Pagamento sem liquidação correspondente", "alta",
    t[["ESTORNO", "DATA", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO", "RETENCOES", "LIQUIDO"]],
    "Pagamento cuja liquidação não existe em nenhuma base carregada. Viola a ordem empenho → liquidação → pagamento "
    "(art. 62 e 63 da Lei 4.320/64). Pode ser liquidação anterior a 2013.",
    "**Base:** Pagamentos do(s) exercício(s) selecionado(s).\n\n**Regra:** a `LIQUIDACAO` citada pelo pagamento não aparece na base de Liquidações **completa** (todos os anos). Nenhum valor é somado — é um teste de existência de chave.",
))

# 2. Liquidação sem empenho -----------------------------------------------------
t = ln[~ln["EMPENHO"].isin(emp["EMPENHO"])]
testes.append((
    "Liquidação sem empenho correspondente", "alta",
    t[["ESTORNO", "DATA", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR", "TIPO_DOCUMENTO", "DESCRICAO"]],
    "Liquidação referenciando empenho inexistente nas bases (art. 60 da Lei 4.320/64 veda despesa sem prévio empenho). "
    "Pode ser empenho anterior a 2013.",
    "**Base:** Liquidações do(s) exercício(s) selecionado(s).\n\n**Regra:** o `EMPENHO` citado pela liquidação não existe na base de Empenhos **completa** (todos os anos). Teste de existência de chave, sem soma de valores.",
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
    "**Chave:** `LIQUIDACAO`.\n\n**Regra:** soma o `VALOR_PAGO` de todos os pagamentos da chave e o `VALOR` de todas as liquidações da mesma chave, sempre nas bases completas e **com os estornos entrando com sinal negativo** (portanto são totais líquidos). Aponta quando PAGO − LIQUIDADO passa da tolerância de valor definida na barra lateral.",
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
    "**Chave:** `EMPENHO`.\n\n**Regra:** soma o `VALOR` das liquidações e o `VALOR` dos empenhos da chave, nas bases completas e líquidos de estornos/anulações. Aponta quando LIQUIDADO − EMPENHADO passa da tolerância de valor.",
))

# 5. Pagamento antes da liquidação ----------------------------------------------
t = pn.assign(DATA_LIQUIDACAO=pn["LIQUIDACAO"].map(data_liq))
t = t[t["DATA_LIQUIDACAO"].notna()]
t = t.assign(DIAS=(t["DATA"] - t["DATA_LIQUIDACAO"]).dt.days)
t = t[t["DIAS"] < dias_pagto] if dias_pagto > 0 else t[t["DIAS"] < 0]
testes.append((
    "Pagamento anterior à data da liquidação", "alta",
    t[["ESTORNO", "DATA", "DATA_LIQUIDACAO", "DIAS", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO"]].sort_values("DIAS"),
    "A data do pagamento é anterior à data da liquidação a que se refere (art. 62 da Lei 4.320/64).",
    "**Regra:** a data da liquidação é a **menor** `DATA` entre os lançamentos normais daquela `LIQUIDACAO` (base completa). DIAS = data do pagamento − data da liquidação.\n\nCom o parâmetro *Pagamento em menos de (dias)* em **0**, aponta apenas DIAS < 0 (pagamento anterior à liquidação); com N > 0, aponta também DIAS < N. Pagamentos cuja liquidação não está na base ficam de fora.",
))

# 6. Liquidação antes do empenho ------------------------------------------------
t = ln.assign(DATA_EMPENHO=ln["EMPENHO"].map(data_emp))
t = t[t["DATA_EMPENHO"].notna() & (t["DATA"] < t["DATA_EMPENHO"])]
testes.append((
    "Liquidação anterior à data do empenho", "alta",
    t[["ESTORNO", "DATA", "DATA_EMPENHO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR", "TIPO_DOCUMENTO"]],
    "A liquidação foi registrada antes do próprio empenho (art. 60 da Lei 4.320/64).",
    "**Regra:** a data do empenho é a **menor** `DATA` entre os lançamentos normais daquele `EMPENHO` (base completa). Aponta a liquidação cuja `DATA` é anterior a essa. Liquidações sem empenho na base ficam de fora (caem no teste 2).",
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
    "**Base:** Empenhos do(s) exercício(s), **apenas os com `MODALIDADE` vazia** (sem licitação informada).\n\n**Regra:** agrupa por exercício + fornecedor (código e nome) + `NATUREZA` e aponta o grupo que tenha 2 ou mais empenhos distintos e soma de `VALOR` acima do limite de dispensa definido na barra lateral.",
))

# 8. Pagamentos possivelmente duplicados ----------------------------------------
# O documento fiscal só existe na base de Liquidações; é trazido para o pagamento
# pela chave LIQUIDACAO. Ficam apenas os casos iguais em documento fiscal E valor.
doc_da_liq = liq[~liq["ESTORNO"]].drop_duplicates("LIQUIDACAO").set_index("LIQUIDACAO")[["TIPO_DOCUMENTO", "SERIE"]]
t = pn[pn["VALOR_PAGO"] != 0].join(doc_da_liq, on="LIQUIDACAO")
t["TIPO_DOCUMENTO"] = t["TIPO_DOCUMENTO"].fillna("")
t["SERIE"] = t["SERIE"].fillna("")
t = t[t["TIPO_DOCUMENTO"] != ""]
ch = ["FORNECEDOR_COD", "TIPO_DOCUMENTO", "SERIE", "VALOR_PAGO"]
t = t[t.duplicated(ch, keep=False)]
t = t[t.groupby(ch, dropna=False)["LIQUIDACAO"].transform("nunique") > 1].sort_values(ch + ["DATA"])
testes.append((
    "Pagamentos possivelmente duplicados", "média",
    t[["ESTORNO", "DATA", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "TIPO_DOCUMENTO", "SERIE", "VALOR_PAGO", "NATUREZA"]],
    "Mesmo fornecedor, **mesmo documento fiscal e mesmo valor pago**, em liquidações diferentes — só entram os casos "
    "iguais nos dois critérios. O documento fiscal vem da liquidação referenciada pelo pagamento, portanto pagamentos "
    "sem liquidação na base, ou com liquidação sem documento informado, ficam de fora deste teste. "
    "Podem ser parcelas legítimas (ex.: contratos com várias unidades) — conferir a nota no processo.",
    "**Regra:** o documento fiscal só existe na base de Liquidações, então é trazido ao pagamento por *join* na chave `LIQUIDACAO` — uma linha por liquidação, de modo que, se a liquidação tiver documentos diferentes, vale o primeiro (≈5% das liquidações da base).\n\nDescarta pagamentos de valor zero e os que ficaram sem documento. Agrupa por fornecedor + `TIPO_DOCUMENTO` + `SERIE` + `VALOR_PAGO` e aponta o grupo com 2 ou mais `LIQUIDACAO` distintas — ou seja, **documento fiscal e valor iguais**, pagos por liquidações diferentes.",
))

# 8b. Pagamentos duplicados por data e valor (independe do documento) -----------
ch = ["FORNECEDOR_COD", "DATA", "VALOR_PAGO"]
t = pn[pn["VALOR_PAGO"] != 0]
t = t[t.duplicated(ch, keep=False)]
t = t[t.groupby(ch, dropna=False)["LIQUIDACAO"].transform("nunique") > 1].sort_values(ch)
testes.append((
    "Pagamentos duplicados por data e valor (sem usar documento fiscal)", "média",
    t[["ESTORNO", "DATA", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO", "NATUREZA"]],
    "Mesmo fornecedor, mesma data e mesmo valor pagos em liquidações diferentes. É a regra anterior deste painel, "
    "mantida em separado por **não** depender do documento fiscal: pega a duplicidade em que o documento foi digitado "
    "diferente, ou não foi informado — casos que o teste acima não enxerga. Em compensação gera bem mais ruído "
    "(folha, contratos com várias unidades, tarifas repetidas), então trate como pista, não como apontamento fechado.",
    "**Regra:** agrupa os pagamentos de valor diferente de zero por fornecedor + `DATA` + `VALOR_PAGO` e aponta o grupo com 2 ou mais `LIQUIDACAO` distintas. O documento fiscal não entra na chave.\n\nÉ independente do teste anterior: cobre o caso em que o documento foi digitado de forma diferente nas duas liquidações, ou não foi informado. Por não usar o documento, aponta bem mais linhas.",
))

# 9. Documento fiscal repetido --------------------------------------------------
ch = ["FORNECEDOR_COD", "TIPO_DOCUMENTO", "SERIE"]
t = ln[ln["TIPO_DOCUMENTO"].fillna("") != ""]
t = t[t.duplicated(ch, keep=False)]
t = t[t.groupby(ch)["LIQUIDACAO"].transform("nunique") > 1].sort_values(ch + ["DATA"])
testes.append((
    "Mesmo documento fiscal em liquidações distintas", "média",
    t[["ESTORNO", "DATA", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "TIPO_DOCUMENTO", "SERIE", "VALOR"]],
    "O mesmo número/série de documento do mesmo fornecedor aparece em mais de uma liquidação. Possível liquidação em duplicidade "
    "(ou nota liquidada em parcelas — verificar se a soma bate com o documento).",
    "**Base:** Liquidações do(s) exercício(s) com `TIPO_DOCUMENTO` preenchido.\n\n**Regra:** agrupa por fornecedor + `TIPO_DOCUMENTO` + `SERIE` — **o valor não entra na chave** — e aponta o grupo com 2 ou mais `LIQUIDACAO` distintas. Por isso pega também a nota liquidada em parcelas, que o teste de pagamento duplicado descarta.",
))

# 10. Lançamentos em fim de semana ----------------------------------------------
def fds(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["DATA"].dt.dayofweek >= 5]


t = pd.concat([
    fds(en).assign(BASE="Empenho", CHAVE=lambda d: d["EMPENHO"], VALOR=lambda d: d["VALOR"]),
    fds(ln).assign(BASE="Liquidação", CHAVE=lambda d: d["LIQUIDACAO"], VALOR=lambda d: d["VALOR"]),
    fds(pn).assign(BASE="Pagamento", CHAVE=lambda d: d["PAGAMENTO"], VALOR=lambda d: d["VALOR_PAGO"]),
])
t = t.assign(DIA=t["DATA"].dt.dayofweek.map({5: "Sábado", 6: "Domingo"}))
testes.append((
    "Lançamentos em sábado ou domingo", "baixa",
    t[["ESTORNO", "BASE", "DATA", "DIA", "CHAVE", "EMPENHO", "FORNECEDOR_NOME", "VALOR"]].sort_values("DATA"),
    "Registros em dias sem expediente. Podem ser legítimos (folha, tarifas bancárias, retroação) mas merecem atenção.",
    "**Regra:** filtra empenhos, liquidações e pagamentos do(s) exercício(s) cuja `DATA` cai em sábado ou domingo e empilha os três numa tabela única, com a coluna BASE indicando a origem e CHAVE o número do documento.",
))

# 11. Empenhos no último dia do exercício -------------------------------------
t = en[(en["DATA"].dt.month == 12) & (en["DATA"].dt.day >= 30)]
testes.append((
    "Empenhos em 30 ou 31 de dezembro", "baixa",
    t[["ESTORNO", "DATA", "EMPENHO", "FORNECEDOR_NOME", "NATUREZA", "VALOR", "DESCRICAO"]].sort_values("VALOR", ascending=False),
    "Empenhos de fim de exercício podem indicar 'empenho de sobra de dotação' para inscrição em restos a pagar sem despesa efetiva.",
    "**Regra:** empenhos do(s) exercício(s) com `DATA` em dezembro, dia 30 ou 31. Ordenados do maior valor para o menor.",
))

# 12. Empenho sem descrição -------------------------------------------------------
t = en[en["DESCRICAO"].fillna("").str.len() < 10]
testes.append((
    "Empenho sem descrição (ou descrição muito curta)", "baixa",
    t[["ESTORNO", "DATA", "EMPENHO", "FORNECEDOR_NOME", "NATUREZA", "VALOR", "DESCRICAO"]],
    "Histórico insuficiente dificulta a verificação do objeto da despesa.",
    "**Regra:** empenhos do(s) exercício(s) cuja `DESCRICAO` tem menos de 10 caracteres, incluindo os vazios.",
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
    "**Regra:** soma o `VALOR` por `EMPENHO` e por `LIQUIDACAO` nas bases completas (estornos negativos) e aponta as chaves do(s) exercício(s) cujo saldo ficou **abaixo de −tolerância** — isto é, os estornos superam o lançamento original. As duas bases são empilhadas com a coluna BASE.",
))

# 13. Empenhos sem qualquer liquidação (saldo integral) -------------------------
saldo = emp_liq_por_emp.reindex(en["EMPENHO"].unique()).to_frame("EMPENHADO")
saldo["LIQUIDADO"] = liq_liq_por_emp.reindex(saldo.index).fillna(0)
t = saldo[(saldo["EMPENHADO"] > tolerancia) & (saldo["LIQUIDADO"] == 0)].join(info_emp).reset_index(names="EMPENHO")
testes.append((
    "Empenhos sem nenhuma liquidação", "info",
    t.sort_values("EMPENHADO", ascending=False),
    "Saldo empenhado integralmente sem liquidação. Normal no exercício corrente; em exercícios encerrados indica restos a pagar não processados.",
    "**Regra:** para cada `EMPENHO` do(s) exercício(s), compara o saldo empenhado (líquido de anulações) com a soma das liquidações da mesma chave na base completa. Aponta quando o saldo é maior que a tolerância e o liquidado é exatamente zero.",
))

# 14. Concentração de fornecedores ----------------------------------------------
tot = pn["VALOR_PAGO"].sum()
t = pn.groupby(["FORNECEDOR_COD", "FORNECEDOR_NOME"]).agg(PAGAMENTOS=("PAGAMENTO", "nunique"), VALOR_PAGO=("VALOR_PAGO", "sum")).reset_index()
t["% DO TOTAL"] = (100 * t["VALOR_PAGO"] / tot).round(2) if tot else 0
t = t.sort_values("VALOR_PAGO", ascending=False).head(30)
testes.append((
    "Concentração de pagamentos por fornecedor (top 30)", "info", t,
    "Informativo: fornecedores que concentram a maior parte dos pagamentos do período.",
    "**Regra:** agrupa os pagamentos do(s) exercício(s) por fornecedor, soma `VALOR_PAGO`, conta os `PAGAMENTO` distintos e calcula o percentual sobre o total pago do período. Mostra os 30 maiores. Não é um teste de irregularidade.",
))

# ---------------------------------------------------------------- resumo
COR = {"alta": "🔴", "média": "🟠", "baixa": "🟡", "info": "🔵"}
resumo = pd.DataFrame(
    [{"Gravidade": f"{COR[g]} {g}", "Teste": titulo, "Apontamentos": len(t)} for titulo, g, t, _, _m in testes]
)
st.subheader("Resumo")
c1, c2, c3, c4 = st.columns(4)
for col, g in zip([c1, c2, c3, c4], ["alta", "média", "baixa", "info"]):
    n = sum(len(t) for _, gg, t, _, _m in testes if gg == g)
    col.metric(f"{COR[g]} Gravidade {g}", f"{n:,}".replace(",", "."))
st.dataframe(resumo, hide_index=True, width="stretch")

# ---------------------------------------------------------------- detalhes
# st.expander só aceita `help` a partir do Streamlit 1.45; em versões anteriores
# o método de cada teste é exibido num popover dentro do próprio expander.
EXPANDER_TEM_HELP = "help" in inspect.signature(st.expander).parameters

st.subheader("Detalhamento")
so_com_apontamento = st.toggle("Mostrar apenas testes com apontamentos", value=True, help="Desligue para listar também os testes que não encontraram nada nos exercícios selecionados.")
for i, (titulo, g, t, explicacao, metodo) in enumerate(testes):
    if so_com_apontamento and t.empty:
        continue
    rotulo = f"{COR[g]} {titulo} — {len(t):,} apontamento(s)".replace(",", ".")
    ajuda = {"help": dados.md(f"**Como este teste é feito**\n\n{metodo}")} if EXPANDER_TEM_HELP else {}
    with st.expander(rotulo, expanded=False, **ajuda):
        if not EXPANDER_TEM_HELP:
            # Streamlit antigo: sem tooltip no expander, o método vai num popover.
            with st.popover("❓ Como este teste é feito"):
                dados.texto(metodo)
        dados.texto(explicacao)
        if t.empty:
            st.success("Nenhum apontamento para os exercícios selecionados.")
            continue
        dados.tabela(t, hide_index=True)
        st.download_button(
            "⬇️ Baixar CSV", t.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            f"irregularidade_{i + 1:02d}.csv", "text/csv", key=f"dl_irr_{i}",
        )
