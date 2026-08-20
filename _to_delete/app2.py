"""
Comparador Empenhado x Liquidado x Pago - Prefeitura de Centenário do Sul
==========================================================================
App em Streamlit que cruza os três relatórios do ciclo da despesa pública
("Relação da despesa líquida empenhada", "...liquidada" e "...paga",
exportados em CSV a partir dos PDFs oficiais) e aponta onde o valor
empenhado diverge do liquidado, e onde o liquidado diverge do pago, para
o mesmo Empenho.

Como rodar:
    pip install -r requirements.txt
    streamlit run app.py

Estrutura de pastas esperada (a mesma que você já organizou):
    realizavel/
      app.py            <- este arquivo
      data/              <- os CSVs (empenhada, liquidada e paga, quaisquer anos)
      pdf/               <- os PDFs originais (não é lido pelo app)
"""

import glob
import os
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Paleta (padrão validado do skill de dataviz interno) - 3 séries em ordem fixa
# ---------------------------------------------------------------------------
COLOR_EMPENHADO = "#2a78d6"   # categorical slot 1 - blue
COLOR_LIQUIDADO = "#eb6834"   # categorical slot 2 - orange
COLOR_PAGO = "#1baf7a"        # categorical slot 3 - aqua
COLOR_GOOD = "#0ca30c"
COLOR_WARNING = "#fab219"
COLOR_SERIOUS = "#ec835a"
COLOR_CRITICAL = "#d03b3b"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"

STATUS_COLORS = {
    "OK (bate em todas as etapas)": COLOR_GOOD,
    "Divergente: liquidado ≠ pago": COLOR_CRITICAL,
    "Divergente: empenhado ≠ liquidado": COLOR_SERIOUS,
    "Pendente de liquidação": COLOR_WARNING,
    "Pendente de pagamento": COLOR_WARNING,
    "Fora do período carregado": COLOR_MUTED,
}

st.set_page_config(
    page_title="Empenhado x Liquidado x Pago - Centenário do Sul",
    page_icon="🧾",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def fmt_brl(value: float) -> str:
    s = f"{value:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_brl_compact(value: float) -> str:
    """Compact BRL for tight KPI cards: R$ 1,2 mi / R$ 340,5 mil."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}R$ {v/1_000_000:,.1f} mi".replace(".", ",")
    if v >= 1_000:
        return f"{sign}R$ {v/1_000:,.1f} mil".replace(".", ",")
    return fmt_brl(value)


def to_float(value: str) -> float:
    """Converte string monetária BR ('1.234,56' ou '-1.234,56') para float."""
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_year(filename: str) -> str:
    m = re.search(r"(20\d{2})", os.path.basename(filename))
    if m:
        return m.group(1)
    return "?"


def extract_ano_empenho(empenho: str) -> str:
    """O próprio número do Empenho traz o ano de origem ('45/2022' -> '2022'),
    o que é mais confiável do que o ano do arquivo CSV (um empenho de 2021
    pode aparecer referenciado em pagamentos de 2022)."""
    if not isinstance(empenho, str):
        return "?"
    m = re.search(r"/(\d{4})$", empenho.strip())
    return m.group(1) if m else "?"


@st.cache_data(show_spinner=False)
def load_data(data_dir: str):
    empenhada_files = sorted(glob.glob(os.path.join(data_dir, "*empenhada*.csv")))
    liquidada_files = sorted(
        f for f in glob.glob(os.path.join(data_dir, "*liquidada*.csv"))
        if "empenhada" not in os.path.basename(f)
    )
    paga_files = sorted(glob.glob(os.path.join(data_dir, "*paga*.csv")))

    def read_all(files):
        frames = []
        for fp in files:
            df = pd.read_csv(fp, sep=";", encoding="utf-8-sig", dtype=str)
            df["Arquivo_Origem"] = os.path.basename(fp)
            df["Ano_Arquivo"] = extract_year(fp)
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    emp = read_all(empenhada_files)
    liq = read_all(liquidada_files)
    pag = read_all(paga_files)

    if not emp.empty:
        emp["Valor_num"] = emp["Valor"].apply(to_float)
    if not liq.empty:
        liq["Valor_num"] = liq["Valor"].apply(to_float)
    if not pag.empty:
        pag["Valor_Pago_num"] = pag["Valor_Pago"].apply(to_float)
        pag["Retencoes_num"] = pag["Retencoes"].apply(to_float)
        pag["Liquido_num"] = pag["Liquido"].apply(to_float)

    return emp, liq, pag, empenhada_files, liquidada_files, paga_files


@st.cache_data(show_spinner=False)
def build_comparison(emp: pd.DataFrame, liq: pd.DataFrame, pag: pd.DataFrame, tol: float) -> pd.DataFrame:
    """Cruza empenhada x liquidada x paga pela chave Empenho (o identificador
    comum às três etapas do ciclo da despesa), somando valores — isso
    neutraliza estornos automaticamente, já que um lançamento original e seu
    estorno compartilham o mesmo Empenho e se cancelam na soma."""

    def group(df, value_cols, prefix):
        if df.empty:
            cols = ["Empenho", "Fornecedor_Nome", "Unidade", "Natureza", f"Data_{prefix}", f"Qtd_{prefix}"] + [
                f"{v}_{prefix}" for v in value_cols
            ]
            return pd.DataFrame(columns=cols)
        agg = {f"{v}_{prefix}": (v, "sum") for v in value_cols}
        g = df.groupby("Empenho", as_index=False).agg(
            Fornecedor_Nome=("Fornecedor_Nome", "first"),
            Unidade=("Unidade", "first"),
            Natureza=("Natureza", "first"),
            **{f"Data_{prefix}": ("Data", "max")},
            **{f"Qtd_{prefix}": (value_cols[0], "count")},
            **agg,
        )
        return g

    emp_g = group(emp, ["Valor_num"], "Empenhado")
    emp_g = emp_g.rename(columns={"Valor_num_Empenhado": "Valor_Empenhado"})
    liq_g = group(liq, ["Valor_num"], "Liquidado")
    liq_g = liq_g.rename(columns={"Valor_num_Liquidado": "Valor_Liquidado"})
    pag_g = group(pag, ["Valor_Pago_num"], "Pago")
    pag_g = pag_g.rename(columns={"Valor_Pago_num_Pago": "Valor_Pago"})

    for g in (emp_g, liq_g, pag_g):
        if "Empenho" not in g.columns:
            g["Empenho"] = pd.Series(dtype=str)

    merged = emp_g.merge(liq_g, on="Empenho", how="outer", suffixes=("", "_liq"))
    merged = merged.merge(pag_g, on="Empenho", how="outer", suffixes=("", "_pag"))

    # nome/unidade/natureza: preferir o que veio da etapa mais completa disponível
    for base_col in ("Fornecedor_Nome", "Unidade", "Natureza"):
        cols = [c for c in (base_col, f"{base_col}_liq", f"{base_col}_pag") if c in merged.columns]
        if len(cols) > 1:
            merged[base_col] = merged[cols[0]]
            for c in cols[1:]:
                merged[base_col] = merged[base_col].fillna(merged[c])
            merged.drop(columns=[c for c in cols[1:]], inplace=True)

    for c in ["Valor_Empenhado", "Valor_Liquidado", "Valor_Pago"]:
        if c not in merged.columns:
            merged[c] = 0.0
        merged[c] = merged[c].fillna(0.0)
    for c in ["Qtd_Empenhado", "Qtd_Liquidado", "Qtd_Pago"]:
        if c not in merged.columns:
            merged[c] = 0
        merged[c] = merged[c].fillna(0).astype(int)

    merged["Ano"] = merged["Empenho"].apply(extract_ano_empenho)
    merged["Diferenca_Emp_Liq"] = merged["Valor_Empenhado"] - merged["Valor_Liquidado"]
    merged["Diferenca_Liq_Pag"] = merged["Valor_Liquidado"] - merged["Valor_Pago"]

    has_emp = merged["Qtd_Empenhado"] > 0
    has_liq = merged["Qtd_Liquidado"] > 0
    has_pag = merged["Qtd_Pago"] > 0

    def classify(row):
        if not row["has_emp"] and (row["has_liq"] or row["has_pag"]):
            return "Fora do período carregado"
        if row["has_emp"] and not row["has_liq"]:
            return "Pendente de liquidação"
        if abs(row["Diferenca_Emp_Liq"]) > tol:
            return "Divergente: empenhado ≠ liquidado"
        if row["has_liq"] and not row["has_pag"]:
            return "Pendente de pagamento"
        if abs(row["Diferenca_Liq_Pag"]) > tol:
            return "Divergente: liquidado ≠ pago"
        return "OK (bate em todas as etapas)"

    merged["has_emp"] = has_emp
    merged["has_liq"] = has_liq
    merged["has_pag"] = has_pag
    merged["Status"] = merged.apply(classify, axis=1)
    merged.drop(columns=["has_emp", "has_liq", "has_pag"], inplace=True)

    return merged


# ---------------------------------------------------------------------------
# Sidebar - fonte de dados
# ---------------------------------------------------------------------------
st.sidebar.title("🧾 Configuração")

data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

if not os.path.isdir(data_dir):
    st.error(f"Pasta não encontrada: {data_dir}")
    st.stop()

emp, liq, pag, empenhada_files, liquidada_files, paga_files = load_data(data_dir)

if emp.empty and liq.empty and pag.empty:
    st.error(
        "Nenhum CSV encontrado. Espera-se arquivos com 'empenhada', 'liquidada' "
        "e/ou 'paga' no nome dentro da pasta configurada."
    )
    st.stop()

tol = st.sidebar.number_input(
    "Tolerância para considerar 'igual' (R$)", min_value=0.0, value=0.01, step=0.01,
    format="%.2f",
)

comp = build_comparison(emp, liq, pag, tol)

# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

anos_disponiveis = sorted(comp["Ano"].dropna().unique().tolist())
anos_default = ["2022"] if "2022" in anos_disponiveis else anos_disponiveis
anos_sel = st.sidebar.multiselect("Ano (do Empenho)", anos_disponiveis, default=anos_default)

status_sel = st.sidebar.multiselect(
    "Status", list(STATUS_COLORS.keys()), default=list(STATUS_COLORS.keys())
)

fornecedor_busca = st.sidebar.text_input("Buscar fornecedor (contém)")

valor_min = st.sidebar.number_input(
    "Diferença mínima em módulo, em qualquer etapa (R$)", min_value=0.0, value=0.0, step=100.0
)

filtered = comp.copy()
if anos_sel:
    filtered = filtered[filtered["Ano"].isin(anos_sel)]
if status_sel:
    filtered = filtered[filtered["Status"].isin(status_sel)]
if fornecedor_busca:
    filtered = filtered[
        filtered["Fornecedor_Nome"].fillna("").str.contains(fornecedor_busca, case=False, na=False)
    ]
if valor_min > 0:
    filtered = filtered[
        (filtered["Diferenca_Emp_Liq"].abs() >= valor_min) | (filtered["Diferenca_Liq_Pag"].abs() >= valor_min)
    ]

# ---------------------------------------------------------------------------
# Cabeçalho + KPIs
# ---------------------------------------------------------------------------
st.title("Empenhado x Liquidado x Pago — Prefeitura de Centenário do Sul")
st.caption(
    "Cruzamento pelo número do Empenho entre os três relatórios do ciclo da "
    "despesa: empenhada, liquidada e paga. Lançamentos e seus estornos com o "
    "mesmo Empenho são somados (isso zera estornos automaticamente)."
)

total_emp = filtered["Valor_Empenhado"].sum()
total_liq = filtered["Valor_Liquidado"].sum()
total_pago = filtered["Valor_Pago"].sum()
n_div_liq_pag = int((filtered["Status"] == "Divergente: liquidado ≠ pago").sum())
n_div_emp_liq = int((filtered["Status"] == "Divergente: empenhado ≠ liquidado").sum())
n_pend_liq = int((filtered["Status"] == "Pendente de liquidação").sum())
n_pend_pag = int((filtered["Status"] == "Pendente de pagamento").sum())
n_ok = int((filtered["Status"] == "OK (bate em todas as etapas)").sum())

c1, c2, c3 = st.columns(3)
c1.metric("Total empenhado (filtro)", fmt_brl_compact(total_emp), help=fmt_brl(total_emp))
c2.metric("Total liquidado (filtro)", fmt_brl_compact(total_liq), help=fmt_brl(total_liq))
c3.metric("Total pago (filtro)", fmt_brl_compact(total_pago), help=fmt_brl(total_pago))

c4, c5, c6, c7, c8 = st.columns(5)
c4.metric("Empenhado ≠ Liquidado", n_div_emp_liq)
c5.metric("Liquidado ≠ Pago", n_div_liq_pag)
c6.metric("Pendente de liquidação", n_pend_liq)
c7.metric("Pendente de pagamento", n_pend_pag)
c8.metric("OK (batendo)", n_ok)

# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
col_a, col_b = st.columns([1, 1])

with col_a:
    st.subheader("Empenhado x Liquidado x Pago por ano")
    by_year = (
        filtered.groupby("Ano")
        .agg(
            Empenhado=("Valor_Empenhado", "sum"),
            Liquidado=("Valor_Liquidado", "sum"),
            Pago=("Valor_Pago", "sum"),
        )
        .reset_index()
        .sort_values("Ano")
    )
    fig = go.Figure()
    fig.add_bar(name="Empenhado", x=by_year["Ano"], y=by_year["Empenhado"], marker_color=COLOR_EMPENHADO)
    fig.add_bar(name="Liquidado", x=by_year["Ano"], y=by_year["Liquidado"], marker_color=COLOR_LIQUIDADO)
    fig.add_bar(name="Pago", x=by_year["Ano"], y=by_year["Pago"], marker_color=COLOR_PAGO)
    fig.update_layout(
        barmode="group",
        plot_bgcolor="#fcfcfb",
        paper_bgcolor="#fcfcfb",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=40, l=10, r=10, b=10),
        yaxis=dict(gridcolor=COLOR_GRID, tickprefix="R$ "),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, width='stretch')

with col_b:
    st.subheader("Distribuição por status")
    status_counts = filtered["Status"].value_counts().reindex(list(STATUS_COLORS.keys())).fillna(0)
    status_counts = status_counts[status_counts > 0] if status_counts.sum() > 0 else status_counts
    fig2 = go.Figure(
        go.Bar(
            x=status_counts.values,
            y=status_counts.index,
            orientation="h",
            marker_color=[STATUS_COLORS[s] for s in status_counts.index],
        )
    )
    fig2.update_layout(
        plot_bgcolor="#fcfcfb",
        paper_bgcolor="#fcfcfb",
        margin=dict(t=20, l=10, r=10, b=10),
        xaxis=dict(gridcolor=COLOR_GRID, title="Nº de registros"),
        yaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig2, width='stretch')

# ---------------------------------------------------------------------------
# Tabela de divergências
# ---------------------------------------------------------------------------
st.subheader(f"Detalhe ({len(filtered):,} registro(s) no filtro atual)".replace(",", "."))

show_cols = [
    "Status", "Empenho", "Ano", "Fornecedor_Nome", "Unidade", "Natureza",
    "Data_Empenhado", "Data_Liquidado", "Data_Pago",
    "Valor_Empenhado", "Valor_Liquidado", "Valor_Pago",
    "Diferenca_Emp_Liq", "Diferenca_Liq_Pag",
    "Qtd_Empenhado", "Qtd_Liquidado", "Qtd_Pago",
]
show_cols = [c for c in show_cols if c in filtered.columns]
display_df = filtered[show_cols].copy()
display_df["_ordenacao"] = filtered[["Diferenca_Emp_Liq", "Diferenca_Liq_Pag"]].abs().max(axis=1)
display_df = display_df.sort_values("_ordenacao", ascending=False).drop(columns=["_ordenacao"])

st.dataframe(
    display_df,
    width='stretch',
    height=480,
    column_config={
        "Valor_Empenhado": st.column_config.NumberColumn("Valor empenhado", format="R$ %.2f"),
        "Valor_Liquidado": st.column_config.NumberColumn("Valor liquidado", format="R$ %.2f"),
        "Valor_Pago": st.column_config.NumberColumn("Valor pago", format="R$ %.2f"),
        "Diferenca_Emp_Liq": st.column_config.NumberColumn("Dif. Empenhado-Liquidado", format="R$ %.2f"),
        "Diferenca_Liq_Pag": st.column_config.NumberColumn("Dif. Liquidado-Pago", format="R$ %.2f"),
        "Qtd_Empenhado": st.column_config.NumberColumn("Nº empenhos"),
        "Qtd_Liquidado": st.column_config.NumberColumn("Nº liquidações"),
        "Qtd_Pago": st.column_config.NumberColumn("Nº pagamentos"),
    },
    hide_index=True,
)

csv_bytes = display_df.to_csv(sep=";", index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    "⬇️ Baixar este resultado em CSV",
    data=csv_bytes,
    file_name=f"empenhado_liquidado_pago_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
    mime="text/csv",
)

# ---------------------------------------------------------------------------
# Consulta de um caso específico
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Consultar um Empenho específico")
emp_input = st.text_input("Número do Empenho (ex: 45/2022)")
if emp_input:
    st.markdown("**Lançamentos de empenho:**")
    st.dataframe(
        emp[emp["Empenho"] == emp_input][
            ["Data", "Reversao_Estorno", "Estorno_Empenho", "Empenho", "Tipo", "Fornecedor_Nome", "Valor", "Arquivo_Origem"]
        ] if not emp.empty else emp,
        hide_index=True,
        width='stretch',
    )
    st.markdown("**Lançamentos de liquidação:**")
    st.dataframe(
        liq[liq["Empenho"] == emp_input][
            ["Data", "Est_Liquidacao", "Liquidacao", "Empenho", "Tipo", "Fornecedor_Nome", "Valor", "Arquivo_Origem"]
        ] if not liq.empty else liq,
        hide_index=True,
        width='stretch',
    )
    st.markdown("**Lançamentos de pagamento:**")
    st.dataframe(
        pag[pag["Empenho"] == emp_input][
            ["Data", "Est_Pgto", "Pagamento", "Liquidacao", "Empenho", "Fornecedor_Nome",
             "Valor_Pago", "Retencoes", "Liquido", "Arquivo_Origem"]
        ] if not pag.empty else pag,
        hide_index=True,
        width='stretch',
    )

st.caption(
    "Observação: itens marcados como 'Fora do período carregado' referem-se a "
    "Empenhos de anos anteriores aos CSVs de empenhada carregados (ex.: uma "
    "liquidação ou pagamento de 2022 referente a um empenho de 2021) — não é "
    "necessariamente uma divergência, apenas falta o CSV daquele ano para "
    "conferir. 'Pendente de liquidação/pagamento' também costuma ser normal: "
    "nem todo empenho é liquidado e pago no mesmo exercício."
)
