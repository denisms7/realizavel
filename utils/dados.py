"""
Camada de acesso aos dados do SCP-550 (Empenhos, Liquidações e Pagamentos).

Os CSVs exportados vêm com algumas particularidades:
  - codificação Latin-1, separador ';', datas dd.mm.aaaa;
  - campos numéricos inteiros com ponto de milhar ("2.013" = 2013);
  - a coluna DESCRICAO pode conter ';' sem aspas, o que desloca as colunas
    seguintes. O leitor abaixo reagrupa os pedaços excedentes na DESCRICAO.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "scp550"

ARQUIVOS = {
    "empenhos": "Empenhos2013a2026.csv",
    "liquidacoes": "Liquidacoes2013a2026.csv",
    "pagamentos": "Pagamentos2013a2026.csv",
}

# Coluna que "absorve" os ';' excedentes quando a linha tem campos a mais.
COLUNA_ABSORVE = {
    "empenhos": "DESCRICAO",
    "liquidacoes": "DESCRICAO",
    "pagamentos": "FORNECEDORES",
}

COLUNAS_DATA = {
    "empenhos": ["DATA"],
    "liquidacoes": ["DATA", "DATA1"],
    "pagamentos": ["DATA"],
}

COLUNAS_VALOR = {
    "empenhos": ["VALOR"],
    "liquidacoes": ["VALOR"],
    "pagamentos": ["VALOR_PAGO", "RETENCOES"],
}

# Inteiros gravados com ponto de milhar ("2.013", "6.952").
COLUNAS_INTEIRO = {
    "empenhos": ["EXERCICIO", "NUMEROEMPENHO"],
    "liquidacoes": ["EXERCICIOLIQUIDACAO", "NUMEROLIQUIDACAO"],
    "pagamentos": ["EXERCICIO", "NRPAGAMENTO"],
}

# Colunas no formato "número/ano" usadas como chave entre as bases.
COLUNAS_CHAVE = {
    "empenhos": ["EMPENHO"],
    "liquidacoes": ["LIQUIDACAO", "EMPENHO"],
    "pagamentos": ["PAGAMENTO", "PREVISAO", "LIQUIDACAO", "EMPENHO"],
}


# --------------------------------------------------------------------------- #
# Leitura bruta
# --------------------------------------------------------------------------- #
def _ler_csv_tolerante(conteudo: str, coluna_absorve: str) -> pd.DataFrame:
    """Lê o CSV linha a linha, corrigindo linhas com ';' dentro de um campo."""
    leitor = csv.reader(io.StringIO(conteudo), delimiter=";")
    cabecalho = next(leitor)
    n = len(cabecalho)
    idx = cabecalho.index(coluna_absorve)

    linhas = []
    for linha in leitor:
        if not linha:
            continue
        extra = len(linha) - n
        if extra > 0:
            junto = ";".join(linha[idx : idx + extra + 1]).strip(";")
            linha = linha[:idx] + [junto] + linha[idx + extra + 1 :]
        elif extra < 0:
            linha = linha + [""] * (-extra)
        linhas.append(linha)

    return pd.DataFrame(linhas, columns=cabecalho)


def _para_float(serie: pd.Series) -> pd.Series:
    """'1234.56' -> 1234.56 ; '-0.00' -> 0.0 ; vazio -> NaN."""
    s = serie.astype("string").str.strip().str.replace(",", ".", regex=False)
    # Negativos entre parênteses: "(700.00)" -> "-700.00"
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return pd.to_numeric(s, errors="coerce").astype("float64")


def _para_inteiro(serie: pd.Series) -> pd.Series:
    """'2.013' -> 2013 (remove ponto de milhar)."""
    s = serie.astype("string").str.strip().str.replace(".", "", regex=False)
    return pd.to_numeric(s, errors="coerce").astype("Int64")


def _para_data(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie, format="%d.%m.%Y", errors="coerce")


def _tratar(df: pd.DataFrame, base: str) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype("string").str.strip()

    for c in COLUNAS_DATA[base]:
        if c in df:
            df[c] = _para_data(df[c])
    for c in COLUNAS_VALOR[base]:
        if c in df:
            df[c] = _para_float(df[c])
    for c in COLUNAS_INTEIRO[base]:
        if c in df:
            df[c] = _para_inteiro(df[c])

    # Ano de referência a partir da chave "número/ano" (mais confiável que EXERCICIO).
    chave = COLUNAS_CHAVE[base][0]
    ano = df[chave].str.extract(r"/(\d{4})$")[0]
    df["ANO"] = pd.to_numeric(ano, errors="coerce").astype("Int64")
    df["MES"] = df["DATA"].dt.to_period("M").astype("string")

    # Código e nome do fornecedor ("35-LUIZ NICACIO" ou "35 LUIZ NICACIO").
    if "FORNECEDORES" in df:
        forn = df["FORNECEDORES"].str.extract(r"^\s*(\d+)\s*[- ]\s*(.*)$")
        df["FORNECEDOR_COD"] = pd.to_numeric(forn[0], errors="coerce").astype("Int64")
        df["FORNECEDOR_NOME"] = forn[1].fillna(df["FORNECEDORES"]).str.strip()

    # Regra do SCP-550: valor negativo é um ESTORNO do lançamento original
    # (anulação de empenho, estorno de liquidação ou de pagamento).
    col_valor = COLUNAS_VALOR[base][0]
    df["ESTORNO"] = df[col_valor].fillna(0) < 0
    df["LANCAMENTO"] = df["ESTORNO"].map({True: "Estorno", False: "Normal"}).astype("string")

    if base == "pagamentos":
        # LIQUIDO vem com formatação inconsistente; recalculado.
        df["LIQUIDO"] = df["VALOR_PAGO"].fillna(0) - df["RETENCOES"].fillna(0)

    return df


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def caminho(base: str) -> Path:
    return PASTA_DADOS / ARQUIVOS[base]


def info_arquivos() -> pd.DataFrame:
    """Tabela com nome, existência, tamanho e data de modificação dos CSVs."""
    linhas = []
    for base, nome in ARQUIVOS.items():
        p = PASTA_DADOS / nome
        existe = p.exists()
        linhas.append(
            {
                "Base": base.capitalize(),
                "Arquivo": nome,
                "Encontrado": "✅" if existe else "❌",
                "Tamanho (MB)": round(p.stat().st_size / 1_048_576, 1) if existe else None,
                "Modificado em": pd.Timestamp(p.stat().st_mtime, unit="s").strftime("%d/%m/%Y %H:%M") if existe else None,
            }
        )
    return pd.DataFrame(linhas)


@st.cache_data(show_spinner="Lendo CSVs do SCP-550...")
def carregar_base(base: str, _mtime: float | None = None) -> pd.DataFrame:
    """Carrega e trata uma base. `_mtime` só serve para invalidar o cache
    quando o arquivo muda em disco."""
    p = caminho(base)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    conteudo = p.read_text(encoding="latin-1")
    bruto = _ler_csv_tolerante(conteudo, COLUNA_ABSORVE[base])
    return _tratar(bruto, base)


def carregar(base: str) -> pd.DataFrame:
    p = caminho(base)
    mtime = p.stat().st_mtime if p.exists() else None
    return carregar_base(base, mtime)


def carregar_tudo() -> dict[str, pd.DataFrame]:
    return {b: carregar(b) for b in ARQUIVOS}


def limpar_cache() -> None:
    carregar_base.clear()


def exigir_base(base: str) -> pd.DataFrame:
    """Uso nas páginas: carrega ou interrompe com mensagem amigável."""
    try:
        return carregar(base)
    except FileNotFoundError as e:
        st.error(f"{e}\n\nVá em **Sistema → Fonte de Dados** para verificar os arquivos.")
        st.stop()


# --------------------------------------------------------------------------- #
# Utilitários de apresentação
# --------------------------------------------------------------------------- #
def brl(valor: float | None) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    s = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def resumo_qualidade(df: pd.DataFrame) -> pd.DataFrame:
    """Nulos, tipo e exemplos por coluna – para a página de fonte de dados."""
    linhas = []
    for c in df.columns:
        s = df[c]
        nulos = int(s.isna().sum() + (s.astype("string") == "").sum()) if s.dtype == "string" else int(s.isna().sum())
        exemplos = s.dropna().astype("string").head(3).tolist()
        linhas.append(
            {
                "Coluna": c,
                "Tipo": str(s.dtype),
                "Nulos/vazios": nulos,
                "% nulos": round(100 * nulos / max(len(df), 1), 1),
                "Distintos": int(s.nunique(dropna=True)),
                "Exemplos": " | ".join(exemplos),
            }
        )
    return pd.DataFrame(linhas)


def filtro_padrao(df: pd.DataFrame, chave: str) -> pd.DataFrame:
    """Barra lateral com filtros comuns (ano, unidade, natureza, fonte, fornecedor, texto)."""
    st.sidebar.header("Filtros")

    tipo = st.sidebar.radio(
        "Lançamentos", ["Todos", "Somente normais", "Somente estornos"], key=f"{chave}_tipo", horizontal=True
    )
    if tipo == "Somente normais":
        df = df[~df["ESTORNO"]]
    elif tipo == "Somente estornos":
        df = df[df["ESTORNO"]]

    anos = sorted(df["ANO"].dropna().unique().tolist())
    sel_anos = st.sidebar.multiselect("Exercício", anos, default=anos[-1:] if anos else [], key=f"{chave}_ano")
    if sel_anos:
        df = df[df["ANO"].isin(sel_anos)]

    for col, rotulo in [("UNIDADE", "Unidade"), ("FONTE", "Fonte"), ("NATUREZA", "Natureza")]:
        if col in df:
            opcoes = sorted(df[col].dropna().unique().tolist())
            sel = st.sidebar.multiselect(rotulo, opcoes, key=f"{chave}_{col}")
            if sel:
                df = df[df[col].isin(sel)]

    if "FORNECEDOR_NOME" in df:
        forn = st.sidebar.text_input("Fornecedor contém", key=f"{chave}_forn")
        if forn:
            df = df[df["FORNECEDOR_NOME"].str.contains(forn, case=False, na=False)]

    if "DESCRICAO" in df:
        txt = st.sidebar.text_input("Descrição contém", key=f"{chave}_desc")
        if txt:
            df = df[df["DESCRICAO"].str.contains(txt, case=False, na=False)]

    return df


COLUNAS_TOTALIZAVEIS = [
    "VALOR", "VALOR_PAGO", "RETENCOES", "LIQUIDO",
    "EMPENHADO", "LIQUIDADO", "SALDO", "PAGO", "A_PAGAR", "DIFERENCA",
]


def tabela(df: pd.DataFrame, **kwargs) -> None:
    """Exibe um DataFrame e, logo abaixo, a linha de totais das colunas de valor."""
    kwargs.setdefault("width", "stretch")
    st.dataframe(df, **kwargs)

    cols = [c for c in COLUNAS_TOTALIZAVEIS if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    partes = [f"**Total** — {len(df):,} registro(s)".replace(",", ".")]
    partes += [f"**{c}:** {brl(df[c].sum())}" for c in cols]
    st.markdown(" &nbsp;·&nbsp; ".join(partes))


def kpis_valor(df: pd.DataFrame, col: str, rotulo: str) -> None:
    """Quatro métricas padrão: registros, bruto (normais), estornos e líquido."""
    normais = df.loc[~df["ESTORNO"], col].sum()
    estornos = -df.loc[df["ESTORNO"], col].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros", f"{len(df):,}".replace(",", "."), help=f"{int(df['ESTORNO'].sum())} estorno(s)")
    c2.metric(f"{rotulo} (bruto)", brl(normais))
    c3.metric("Estornos", brl(estornos))
    c4.metric(f"{rotulo} líquido", brl(normais - estornos))
