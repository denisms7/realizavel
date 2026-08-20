"""
Comparador Liquidado x Pago - Prefeitura de Centenário do Sul
================================================================
App em Streamlit que cruza os relatórios "Relação da despesa líquida
liquidada" e "Relação da despesa líquida paga" (exportados em CSV a partir
dos PDFs oficiais) e aponta onde o valor liquidado diverge do valor
efetivamente pago para a mesma Liquidação/Empenho.

Como rodar:
    pip install -r requirements.txt
    streamlit run app.py

Estrutura de pastas esperada (a mesma que você já organizou):
    realizavel/
      app.py            <- este arquivo
      data/              <- os CSVs (liquidada e paga, quaisquer anos)
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
# Paleta (padrão validado do skill de dataviz interno)
# ---------------------------------------------------------------------------
COLOR_LIQUIDADO = "#2a78d6"   # categorical slot 1 - blue
COLOR_PAGO = "#eb6834"        # categorical slot 2 - orange
COLOR_GOOD = "#0ca30c"
COLOR_WARNING = "#fab219"
COLOR_SERIOUS = "#ec835a"
COLOR_CRITICAL = "#d03b3b"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"

STATUS_COLORS = {
    "OK (bate)": COLOR_GOOD,
    "Divergente": COLOR_CRITICAL,
    "Pendente de pagamento": COLOR_WARNING,
    "Pago fora do período carregado": COLOR_MUTED,
}

st.set_page_config(
    page_title="Liquidado x Pago - Centenário do Sul",
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


@st.cache_data(show_spinner=False)
def load_data(data_dir: str):
    liquidada_files = sorted(glob.glob(os.path.join(data_dir, "*liquidada*.csv")))
    paga_files = sorted(glob.glob(os.path.join(data_dir, "*paga*.csv")))

    liq_frames = []
    for fp in liquidada_files:
        df = pd.read_csv(fp, sep=";", encoding="utf-8-sig", dtype=str)
        df["Arquivo_Origem"] = os.path.basename(fp)
        df["Ano_Arquivo"] = extract_year(fp)
        liq_frames.append(df)

    pag_frames = []
    for fp in paga_files:
        df = pd.read_csv(fp, sep=";", encoding="utf-8-sig", dtype=str)
        df["Arquivo_Origem"] = os.path.basename(fp)
        df["Ano_Arquivo"] = extract_year(fp)
        pag_frames.append(df)

    liq = pd.concat(liq_frames, ignore_index=True) if liq_frames else pd.DataFrame()
    pag = pd.concat(pag_frames, ignore_index=True) if pag_frames else pd.DataFrame()

    if not liq.empty:
        liq["Valor_num"] = liq["Valor"].apply(to_float)
    if not pag.empty:
        pag["Valor_Pago_num"] = pag["Valor_Pago"].apply(to_float)
        pag["Retencoes_num"] = pag["Retencoes"].apply(to_float)
        pag["Liquido_num"] = pag["Liquido"].apply(to_float)

    return liq, pag, liquidada_files, paga_files


@st.cache_data(show_spinner=False)
def build_comparison(liq: pd.DataFrame, pag: pd.DataFrame, tol: float) -> pd.DataFrame:
    """Cruza liquidada x paga pela chave (Liquidacao, Empenho), somando valores
    (isso neutraliza estornos: um lançamento original + seu estorno com o
    mesmo par Liquidacao/Empenho somam zero dos dois lados)."""

    if liq.empty and pag.empty:
        return pd.DataFrame()

    liq_g = (
        liq.groupby(["Liquidacao", "Empenho"], as_index=False)
        .agg(
            Valor_Liquidado=("Valor_num", "sum"),
            Fornecedor_Nome=("Fornecedor_Nome", "first"),
            Fornecedor_Codigo=("Fornecedor_Codigo", "first"),
            Natureza=("Natureza", "first"),
            Unidade=("Unidade", "first"),
            Data_Liquidacao=("Data", "max"),
            Ano_Liquidacao=("Ano_Arquivo", "first"),
            Qtd_Lancamentos_Liquidados=("Valor_num", "count"),
        )
        if not liq.empty
        else pd.DataFrame(
            columns=[
                "Liquidacao", "Empenho", "Valor_Liquidado", "Fornecedor_Nome",
                "Fornecedor_Codigo", "Natureza", "Unidade", "Data_Liquidacao",
                "Ano_Liquidacao", "Qtd_Lancamentos_Liquidados",
            ]
        )
    )

    pag_g = (
        pag.groupby(["Liquidacao", "Empenho"], as_index=False)
        .agg(
            Valor_Pago=("Valor_Pago_num", "sum"),
            Retencoes=("Retencoes_num", "sum"),
            Liquido_Pago=("Liquido_num", "sum"),
            Fornecedor_Nome_pag=("Fornecedor_Nome", "first"),
            Data_Pagamento=("Data", "max"),
            Ano_Pagamento=("Ano_Arquivo", "first"),
            Qtd_Pagamentos=("Valor_Pago_num", "count"),
        )
        if not pag.empty
        else pd.DataFrame(
            columns=[
                "Liquidacao", "Empenho", "Valor_Pago", "Retencoes", "Liquido_Pago",
                "Fornecedor_Nome_pag", "Data_Pagamento", "Ano_Pagamento", "Qtd_Pagamentos",
            ]
        )
    )

    merged = pd.merge(liq_g, pag_g, on=["Liquidacao", "Empenho"], how="outer")
    merged["Fornecedor_Nome"] = merged["Fornecedor_Nome"].fillna(merged["Fornecedor_Nome_pag"])
    merged.drop(columns=["Fornecedor_Nome_pag"], inplace=True)
    merged["Valor_Liquidado"] = merged["Valor_Liquidado"].fillna(0.0)
    merged["Valor_Pago"] = merged["Valor_Pago"].fillna(0.0)
    merged["Liquido_Pago"] = merged["Liquido_Pago"].fillna(0.0)
    merged["Retencoes"] = merged["Retencoes"].fillna(0.0)
    merged["Qtd_Lancamentos_Liquidados"] = merged["Qtd_Lancamentos_Liquidados"].fillna(0).astype(int)
    merged["Qtd_Pagamentos"] = merged["Qtd_Pagamentos"].fillna(0).astype(int)

    merged["Diferenca"] = merged["Valor_Liquidado"] - merged["Valor_Pago"]

    has_liq = merged["Qtd_Lancamentos_Liquidados"] > 0
    has_pag = merged["Qtd_Pagamentos"] > 0

    def classify(row):
        if row["has_liq"] and not row["has_pag"]:
            return "Pendente de pagamento"
        if row["has_pag"] and not row["has_liq"]:
            return "Pago fora do período carregado"
        if abs(row["Diferenca"]) > tol:
            return "Divergente"
        return "OK (bate)"

    merged["has_liq"] = has_liq
    merged["has_pag"] = has_pag
    merged["Status"] = merged.apply(classify, axis=1)
    merged.drop(columns=["has_liq", "has_pag"], inplace=True)

    return merged


# ---------------------------------------------------------------------------
# Sidebar - fonte de dados
# ---------------------------------------------------------------------------
st.sidebar.title("🧾 Configuração")

default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
data_dir = st.sidebar.text_input("Pasta com os CSVs", value=default_dir)

if st.sidebar.button("🔄 Recarregar dados"):
    st.cache_data.clear()

if not os.path.isdir(data_dir):
    st.error(f"Pasta não encontrada: {data_dir}")
    st.stop()

liq, pag, liquidada_files, paga_files = load_data(data_dir)

if liq.empty and pag.empty:
    st.error(
        "Nenhum CSV encontrado. Espera-se arquivos com 'liquidada' e 'paga' "
        "no nome dentro da pasta configurada."
    )
    st.stop()

st.sidebar.caption(f"Liquidada: {len(liquidada_files)} arquivo(s)")
for f in liquidada_files:
    st.sidebar.caption(f"　• {os.path.basename(f)}")
st.sidebar.caption(f"Paga: {len(paga_files)} arquivo(s)")
for f in paga_files:
    st.sidebar.caption(f"　• {os.path.basename(f)}")

tol = st.sidebar.number_input(
    "Tolerância para considerar 'igual' (R$)", min_value=0.0, value=0.01, step=0.01,
    format="%.2f",
)

comp = build_comparison(liq, pag, tol)

# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Filtros")

anos_disponiveis = sorted(
    set(comp["Ano_Liquidacao"].dropna().tolist()) | set(comp["Ano_Pagamento"].dropna().tolist())
)
anos_sel = st.sidebar.multiselect("Ano", anos_disponiveis, default=anos_disponiveis)

status_sel = st.sidebar.multiselect(
    "Status", list(STATUS_COLORS.keys()), default=list(STATUS_COLORS.keys())
)

fornecedor_busca = st.sidebar.text_input("Buscar fornecedor (contém)")

valor_min = st.sidebar.number_input("Diferença mínima em módulo (R$)", min_value=0.0, value=0.0, step=100.0)

filtered = comp.copy()
if anos_sel:
    filtered = filtered[
        filtered["Ano_Liquidacao"].isin(anos_sel) | filtered["Ano_Pagamento"].isin(anos_sel)
    ]
if status_sel:
    filtered = filtered[filtered["Status"].isin(status_sel)]
if fornecedor_busca:
    filtered = filtered[
        filtered["Fornecedor_Nome"].fillna("").str.contains(fornecedor_busca, case=False, na=False)
    ]
if valor_min > 0:
    filtered = filtered[filtered["Diferenca"].abs() >= valor_min]

# ---------------------------------------------------------------------------
# Cabeçalho + KPIs
# ---------------------------------------------------------------------------
st.title("Liquidado x Pago — Prefeitura de Centenário do Sul")
st.caption(
    "Cruzamento por Liquidação + Empenho entre os relatórios de despesa "
    "líquida liquidada e paga. Lançamentos e seus estornos com o mesmo par "
    "Liquidação/Empenho são somados (isso zera estornos automaticamente)."
)

total_liq = filtered["Valor_Liquidado"].sum()
total_pago = filtered["Valor_Pago"].sum()
total_dif = filtered.loc[filtered["Status"] == "Divergente", "Diferenca"].abs().sum()
n_divergente = int((filtered["Status"] == "Divergente").sum())
n_pendente = int((filtered["Status"] == "Pendente de pagamento").sum())
n_ok = int((filtered["Status"] == "OK (bate)").sum())

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total liquidado (filtro)", fmt_brl_compact(total_liq), help=fmt_brl(total_liq))
c2.metric("Total pago (filtro)", fmt_brl_compact(total_pago), help=fmt_brl(total_pago))
c3.metric(
    "Registros divergentes", n_divergente,
    delta=fmt_brl_compact(total_dif), delta_color="inverse", help=fmt_brl(total_dif),
)
c4.metric("Pendentes de pagamento", n_pendente)
c5.metric("OK (batendo)", n_ok)

# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
col_a, col_b = st.columns([1, 1])

with col_a:
    st.subheader("Liquidado x Pago por ano")
    by_year = (
        filtered.groupby(filtered["Ano_Liquidacao"].where(filtered["Ano_Liquidacao"] != "?", filtered["Ano_Pagamento"]))
        .agg(Liquidado=("Valor_Liquidado", "sum"), Pago=("Valor_Pago", "sum"))
        .reset_index(names="Ano")
        .sort_values("Ano")
    )
    fig = go.Figure()
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
    "Status", "Liquidacao", "Empenho", "Fornecedor_Nome", "Unidade", "Natureza",
    "Data_Liquidacao", "Data_Pagamento", "Valor_Liquidado", "Valor_Pago", "Diferenca",
    "Qtd_Lancamentos_Liquidados", "Qtd_Pagamentos",
]
display_df = filtered[show_cols].sort_values("Diferenca", key=lambda s: s.abs(), ascending=False)

st.dataframe(
    display_df,
    width='stretch',
    height=480,
    column_config={
        "Valor_Liquidado": st.column_config.NumberColumn("Valor liquidado", format="R$ %.2f"),
        "Valor_Pago": st.column_config.NumberColumn("Valor pago", format="R$ %.2f"),
        "Diferenca": st.column_config.NumberColumn("Diferença", format="R$ %.2f"),
        "Qtd_Lancamentos_Liquidados": st.column_config.NumberColumn("Nº liquidações"),
        "Qtd_Pagamentos": st.column_config.NumberColumn("Nº pagamentos"),
    },
    hide_index=True,
)

csv_bytes = display_df.to_csv(sep=";", index=False, encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    "⬇️ Baixar este resultado em CSV",
    data=csv_bytes,
    file_name=f"liquidado_x_pago_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
    mime="text/csv",
)

# ---------------------------------------------------------------------------
# Consulta de um caso específico
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Consultar uma Liquidação específica")
liq_input = st.text_input("Número da Liquidação (ex: 45/2022)")
if liq_input:
    st.markdown("**Lançamentos de liquidação:**")
    st.dataframe(
        liq[liq["Liquidacao"] == liq_input][
            ["Data", "Est_Liquidacao", "Liquidacao", "Empenho", "Tipo", "Fornecedor_Nome", "Valor", "Arquivo_Origem"]
        ],
        hide_index=True,
        width='stretch',
    )
    st.markdown("**Lançamentos de pagamento:**")
    st.dataframe(
        pag[pag["Liquidacao"] == liq_input][
            ["Data", "Est_Pgto", "Pagamento", "Liquidacao", "Empenho", "Fornecedor_Nome",
             "Valor_Pago", "Retencoes", "Liquido", "Arquivo_Origem"]
        ],
        hide_index=True,
        width='stretch',
    )

st.caption(
    "Observação: itens marcados como 'Pago fora do período carregado' referem-se "
    "a Liquidações de anos anteriores aos CSVs carregados (ex.: pagamento em "
    "2022 de uma liquidação de 2021) — não é necessariamente uma divergência, "
    "apenas falta o CSV daquele ano para conferir."
)
