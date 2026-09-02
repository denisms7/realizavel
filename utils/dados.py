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
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "data" / "scp550"
PASTA_EXTRATOS = RAIZ / "data" / "extratos"

ARQUIVOS = {
    "empenhos": "Empenhos2013a2026.csv",
    "liquidacoes": "Liquidacoes2013a2026.csv",
    "pagamentos": "Pagamentos2013a2026.csv",
}

# Colunas que podem conter ';' sem aspas (deslocando as colunas seguintes),
# em ordem de probabilidade. O leitor testa cada hipótese e fica com a primeira
# em que as colunas numéricas/datas voltam a fazer sentido.
COLUNAS_ABSORVEM = {
    "empenhos": ["DESCRICAO", "FORNECEDORES", "MODALIDADE"],
    "liquidacoes": ["DESCRICAO", "FORNECEDORES", "TIPO_DOCUMENTO", "SERVIDOR_AUTORIZACAO"],
    "pagamentos": ["FORNECEDORES"],
}

# Padrões usados para validar uma linha reconstruída.
_RE_DATA = r"^(\d{2}\.\d{2}\.\d{4})?$"
_RE_NUM = r"^(\(?-?[\d.]+\)?)?$"
VALIDACAO_LINHA = {
    "empenhos": {"DATA": _RE_DATA, "VALOR": _RE_NUM, "EXERCICIO": _RE_NUM, "NUMEROEMPENHO": _RE_NUM},
    "liquidacoes": {"DATA": _RE_DATA, "DATA1": _RE_DATA, "VALOR": _RE_NUM, "EXERCICIOLIQUIDACAO": _RE_NUM, "NUMEROLIQUIDACAO": _RE_NUM},
    "pagamentos": {"DATA": _RE_DATA, "VALOR_PAGO": _RE_NUM, "RETENCOES": _RE_NUM, "EXERCICIO": _RE_NUM, "NRPAGAMENTO": _RE_NUM},
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
def _ler_csv_tolerante(conteudo: str, base: str) -> pd.DataFrame:
    """Lê o CSV linha a linha, corrigindo linhas com ';' dentro de um campo."""
    leitor = csv.reader(io.StringIO(conteudo), delimiter=";")
    cabecalho = next(leitor)
    n = len(cabecalho)
    candidatos = [cabecalho.index(c) for c in COLUNAS_ABSORVEM[base] if c in cabecalho]
    validadores = [(cabecalho.index(c), re.compile(rx)) for c, rx in VALIDACAO_LINHA[base].items() if c in cabecalho]

    def pontua(linha: list[str]) -> int:
        """-1 se alguma coluna validada tem conteúdo inválido; senão, quantas
        colunas validadas estão preenchidas (quanto mais, melhor a hipótese)."""
        pontos = 0
        for i, rx in validadores:
            v = linha[i].strip()
            if not rx.match(v):
                return -1
            if v:
                pontos += 1
        return pontos

    def absorve(linha: list[str], idx: int, k: int) -> list[str]:
        junto = ";".join(linha[idx : idx + k + 1]).strip("; ")
        return linha[:idx] + [junto] + linha[idx + k + 1 :]

    linhas = []
    for linha in leitor:
        if not linha:
            continue
        extra = len(linha) - n
        if extra > 0:
            hipoteses = [absorve(linha, idx, extra) for idx in candidatos]
            # ';' extras repartidos entre duas colunas candidatas
            for a_, i1 in enumerate(candidatos):
                for i2 in candidatos[a_ + 1 :]:
                    for k in range(1, extra):
                        hipoteses.append(absorve(absorve(linha, i2, extra - k), i1, k))
            melhor = max(hipoteses, key=pontua)
            linha = melhor if pontua(melhor) >= 0 else hipoteses[0]
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


def _para_float_br(serie: pd.Series) -> pd.Series:
    """'1.234,56' -> 1234.56 (formato dos extratos bancários)."""
    s = serie.astype("string").str.strip()
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce").astype("float64")


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

    # Em Empenhos e Liquidações, nas linhas de estorno a coluna-chave (EMPENHO /
    # LIQUIDACAO) traz o número do PRÓPRIO estorno; o lançamento original está em
    # NUMERO.../EXERCICIO... . Regravamos a chave para apontar ao original e
    # guardamos o número do estorno em <CHAVE>_ESTORNO. (Em Pagamentos a chave já
    # aponta ao pagamento original.)
    if base in ("empenhos", "liquidacoes"):
        chave = COLUNAS_CHAVE[base][0]
        num, exe = COLUNAS_INTEIRO[base][1], COLUNAS_INTEIRO[base][0]
        original = df[num].astype("string") + "/" + df[exe].astype("string")
        ok = df["ESTORNO"] & df[num].notna() & df[exe].notna()
        df[f"{chave}_ESTORNO"] = df[chave].where(df["ESTORNO"], pd.NA)
        df[chave] = df[chave].mask(ok, original)
        # ANO/MES recalculados com a chave corrigida
        ano = df[chave].str.extract(r"/(\d{4})$")[0]
        df["ANO"] = pd.to_numeric(ano, errors="coerce").astype("Int64")

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
                "Modificado em": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M") if existe else None,
            }
        )
    return pd.DataFrame(linhas)


@st.cache_data(show_spinner="Lendo CSVs do SCP-550...")
def carregar_base(base: str, mtime: float | None = None) -> pd.DataFrame:
    """Carrega e trata uma base. `mtime` entra na chave do cache só para
    invalidá-lo quando o arquivo muda em disco."""
    p = caminho(base)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    conteudo = p.read_text(encoding="latin-1")
    bruto = _ler_csv_tolerante(conteudo, base)
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
# Extratos bancários (data/extratos/*.csv)
# --------------------------------------------------------------------------- #
# Lançamentos que apenas movimentam a aplicação financeira da própria conta:
# não são despesa e portanto não têm empenho/liquidação/pagamento.
HISTORICO_INTERNO = r"APLIC|RESGATE|BB CP|APL\.AUT"


def extratos_disponiveis() -> list[str]:
    if not PASTA_EXTRATOS.is_dir():
        return []
    return sorted(p.name for p in PASTA_EXTRATOS.glob("*.csv"))


@st.cache_data(show_spinner="Lendo extrato bancário...")
def carregar_extrato(nome: str, mtime: float | None = None) -> pd.DataFrame:
    """Lê um extrato de `data/extratos/`. `mtime` só invalida o cache."""
    p = PASTA_EXTRATOS / nome
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    df = pd.read_csv(p, sep=";", encoding="utf-8-sig", dtype="string")
    df.columns = [c.strip() for c in df.columns]

    df["DATA"] = _para_data(df["Data_Contabil"])
    df["VALOR"] = _para_float_br(df["Valor"])
    df["TIPO"] = df["Tipo"].str.strip().str.upper()
    # "Saldo anterior" e linhas sem valor não são lançamentos.
    df = df[df["TIPO"].isin(["C", "D"]) & df["VALOR"].notna() & df["DATA"].notna()].copy()

    df["MOVIMENTO"] = df["TIPO"].map({"C": "Crédito", "D": "Débito"}).astype("string")
    df["VALOR_SINAL"] = df["VALOR"].where(df["TIPO"] == "C", -df["VALOR"])
    df["INTERNO"] = df["Historico"].str.contains(HISTORICO_INTERNO, case=False, na=False, regex=True)
    df["CHEQUE"] = df["Eh_Cheque"].str.strip().str.casefold().eq("sim")
    df["ANO"] = df["DATA"].dt.year.astype("Int64")
    df["MES"] = df["DATA"].dt.to_period("M").astype("string")
    for c in ("Historico", "Detalhe", "Documento"):
        if c in df:
            df[c] = df[c].fillna("")
    return df.reset_index(drop=True)


def exigir_extrato(nome: str) -> pd.DataFrame:
    p = PASTA_EXTRATOS / nome
    try:
        return carregar_extrato(nome, p.stat().st_mtime if p.exists() else None)
    except FileNotFoundError as e:
        st.error(f"{e}\n\nColoque o arquivo em `data/extratos/` e recarregue a página.")
        st.stop()


def bytes_extrato(nome: str) -> bytes:
    """Conteúdo bruto de um arquivo de `data/extratos/` (CSV ou PDF), para download."""
    return (PASTA_EXTRATOS / nome).read_bytes()


def conciliar_com_pagamentos(
    extrato: pd.DataFrame, pagamentos: pd.DataFrame, janela: int = 5, decimais: int = 2
) -> pd.DataFrame:
    """Para cada lançamento do extrato, procura pagamentos do SCP-550 de **mesmo valor**.

    Não existe chave comum entre o extrato e o SCP-550 (o extrato não traz empenho,
    liquidação nem conta de dotação), então o cruzamento é por valor + proximidade de
    data. Devolve uma linha por lançamento do extrato com o candidato mais próximo.
    """
    import numpy as np

    pn = pagamentos[~pagamentos["ESTORNO"]]
    alvo = extrato["VALOR"].round(decimais).to_numpy()
    datas = extrato["DATA"].to_numpy()

    # Índice valor -> posições em `pn`, considerando bruto e líquido de retenções.
    posicoes: dict[float, list[int]] = {}
    for col in ("VALOR_PAGO", "LIQUIDO"):
        for v, pos in pd.Series(range(len(pn))).groupby(pn[col].round(decimais).to_numpy()):
            posicoes.setdefault(float(v), []).extend(pos.tolist())

    pn_datas = pn["DATA"].to_numpy()
    melhor, n_cand, n_janela = [], [], []
    for v, d in zip(alvo, datas):
        pos = posicoes.get(float(v))
        if not pos:
            melhor.append(-1); n_cand.append(0); n_janela.append(0)
            continue
        pos = np.array(sorted(set(pos)))
        dias = np.abs((pn_datas[pos] - d).astype("timedelta64[D]").astype(int))
        melhor.append(int(pos[dias.argmin()]))
        n_cand.append(len(pos))
        n_janela.append(int((dias <= janela).sum()))

    out = extrato.copy()
    out["CANDIDATOS"] = n_cand
    out["CANDIDATOS_NA_JANELA"] = n_janela

    achou = np.array(melhor) >= 0
    cols = ["DATA", "PAGAMENTO", "LIQUIDACAO", "EMPENHO", "FORNECEDOR_NOME", "VALOR_PAGO", "RETENCOES", "LIQUIDO"]
    vazio = pd.DataFrame(index=out.index, columns=[f"PAG_{c}" for c in cols], dtype="object")
    if achou.any():
        m = pn.iloc[[i for i in melhor if i >= 0]][cols].reset_index(drop=True)
        m.index = out.index[achou]
        vazio.loc[achou, :] = m.rename(columns={c: f"PAG_{c}" for c in cols}).values
    out = pd.concat([out, vazio], axis=1)
    out["PAG_DATA"] = pd.to_datetime(out["PAG_DATA"], errors="coerce")
    out["DIAS"] = (out["DATA"] - out["PAG_DATA"]).dt.days

    def classificar(r) -> str:
        if r["CANDIDATOS"] == 0:
            return "Sem pagamento desse valor"
        if pd.isna(r["DIAS"]):
            return "Sem pagamento desse valor"
        if r["DIAS"] == 0:
            return "Conciliado — mesmo dia"
        if abs(r["DIAS"]) <= janela:
            return f"Conciliado — até {janela} dia(s)"
        return "Valor existe, data distante"

    out["STATUS"] = out.apply(classificar, axis=1).astype("string")

    # Um valor redondo (R$ 500,00) casa com centenas de pagamentos: a conciliação
    # só identifica o lançamento quando há UM candidato na janela.
    def confianca(r) -> str:
        if not str(r["STATUS"]).startswith("Conciliado"):
            return "—"
        return "Única" if r["CANDIDATOS_NA_JANELA"] <= 1 else f"Ambígua ({r['CANDIDATOS_NA_JANELA']})"

    out["CONFIANCA"] = out.apply(confianca, axis=1).astype("string")
    return out


# --------------------------------------------------------------------------- #
# Utilitários de apresentação
# --------------------------------------------------------------------------- #
def brl(valor: float | None) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    s = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def md(texto: str) -> str:
    """Escapa `$` para o Markdown do Streamlit não interpretar "R$ ... R$" como fórmula LaTeX."""
    return texto.replace("$", "\\$")


def texto(conteudo: str) -> None:
    """st.markdown seguro para textos com valores em R$."""
    st.markdown(md(conteudo))


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


AJUDA_FILTROS = {
    "tipo": (
        "Separa os lançamentos pelo sinal do valor.\n\n"
        "- **Todos**: normais e estornos juntos (os totais ficam líquidos, pois o estorno é negativo).\n"
        "- **Somente normais**: apenas valores positivos — o que foi efetivamente empenhado/liquidado/pago.\n"
        "- **Somente estornos**: apenas valores negativos — anulações e estornos.\n\n"
        "É aplicado antes dos demais filtros, por isso as opções deles mudam conforme a escolha."
    ),
    "ano": (
        "Exercício de referência, extraído do número do documento (ex.: `123/2024` → 2024). "
        "Nos estornos, é o exercício do lançamento **original** estornado, não a data do estorno.\n\n"
        "Aceita vários anos. Por padrão vem o mais recente; deixe vazio para ver todos."
    ),
    "UNIDADE": (
        "Unidade orçamentária (órgão/secretaria) no formato `órgão.unidade`, ex.: `06.003`. "
        "Selecione uma ou mais; vazio = todas. Linhas de restos a pagar podem vir sem unidade e ficam de fora quando há seleção."
    ),
    "FONTE": (
        "Fonte de recursos (código de 5 dígitos, ex.: `00000` = recursos livres, `00303` = saúde). "
        "Selecione uma ou mais; vazio = todas."
    ),
    "NATUREZA": (
        "Natureza da despesa (categoria.grupo.modalidade.elemento…), ex.: `3.390.390.000` = outros serviços de terceiros – PJ. "
        "Selecione uma ou mais; vazio = todas."
    ),
    "forn": (
        "Busca por trecho do **nome** do fornecedor, sem diferenciar maiúsculas/minúsculas "
        "(ex.: `sanepar` encontra `SANEPAR-COMPANHIA DE SANEAM.DO PARANA`). "
        "Vazio = não filtra. Para acentos, digite exatamente como está na base."
    ),
    "desc": (
        "Busca por trecho do histórico/descrição do lançamento, sem diferenciar maiúsculas/minúsculas. "
        "Na base original os acentos vieram como `.` (ex.: `AQUISI..O`), então prefira palavras sem acento."
    ),
}


def filtro_padrao(df: pd.DataFrame, chave: str) -> pd.DataFrame:
    """Barra lateral com filtros comuns (ano, unidade, natureza, fonte, fornecedor, texto)."""
    st.sidebar.header("Filtros", help="Os filtros são cumulativos (E lógico) e valem para os indicadores, gráficos, tabelas e para o CSV exportado da página.")

    tipo = st.sidebar.radio(
        "Lançamentos", ["Todos", "Somente normais", "Somente estornos"],
        key=f"{chave}_tipo", horizontal=True, help=AJUDA_FILTROS["tipo"],
    )
    if tipo == "Somente normais":
        df = df[~df["ESTORNO"]]
    elif tipo == "Somente estornos":
        df = df[df["ESTORNO"]]

    anos = sorted(df["ANO"].dropna().unique().tolist())
    sel_anos = st.sidebar.multiselect(
        "Exercício", anos, default=anos[-1:] if anos else [], key=f"{chave}_ano", help=AJUDA_FILTROS["ano"],
    )
    if sel_anos:
        df = df[df["ANO"].isin(sel_anos)]

    for col, rotulo in [("UNIDADE", "Unidade"), ("FONTE", "Fonte"), ("NATUREZA", "Natureza")]:
        if col in df:
            opcoes = sorted(df[col].dropna().unique().tolist())
            sel = st.sidebar.multiselect(rotulo, opcoes, key=f"{chave}_{col}", help=AJUDA_FILTROS[col])
            if sel:
                df = df[df[col].isin(sel)]

    if "FORNECEDOR_NOME" in df:
        forn = st.sidebar.text_input("Fornecedor contém", key=f"{chave}_forn", help=AJUDA_FILTROS["forn"])
        if forn:
            df = df[df["FORNECEDOR_NOME"].str.contains(forn, case=False, na=False, regex=False)]

    if "DESCRICAO" in df:
        txt = st.sidebar.text_input("Descrição contém", key=f"{chave}_desc", help=AJUDA_FILTROS["desc"])
        if txt:
            df = df[df["DESCRICAO"].str.contains(txt, case=False, na=False, regex=False)]

    return df


COLUNAS_TOTALIZAVEIS = [
    "VALOR", "VALOR_PAGO", "RETENCOES", "LIQUIDO",
    "EMPENHADO", "LIQUIDADO", "SALDO", "PAGO", "A_PAGAR", "DIFERENCA",
]


def tabela(df: pd.DataFrame, **kwargs) -> None:
    """Exibe um DataFrame e, logo abaixo, a linha de totais das colunas de valor."""
    kwargs.setdefault("width", "stretch")
    if "ESTORNO" in df.columns:
        cfg = dict(kwargs.get("column_config") or {})
        cfg.setdefault("ESTORNO", st.column_config.CheckboxColumn(
            "Estorno", disabled=True,
            help="Marcado quando a linha é um estorno/anulação (valor negativo no SCP-550).",
        ))
        kwargs["column_config"] = cfg
    st.dataframe(df, **kwargs)

    cols = [c for c in COLUNAS_TOTALIZAVEIS if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    partes = [f"**Total** — {len(df):,} registro(s)".replace(",", ".")]
    partes += [f"**{c}:** {brl(df[c].sum())}" for c in cols]
    texto(" &nbsp;·&nbsp; ".join(partes))


def kpis_valor(df: pd.DataFrame, col: str, rotulo: str) -> None:
    """Quatro métricas padrão: registros, bruto (normais), estornos e líquido."""
    normais = df.loc[~df["ESTORNO"], col].sum()
    estornos = -df.loc[df["ESTORNO"], col].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros", f"{len(df):,}".replace(",", "."), help=f"{int(df['ESTORNO'].sum())} estorno(s)")
    c2.metric(f"{rotulo} (bruto)", brl(normais))
    c3.metric("Estornos", brl(estornos))
    c4.metric(f"{rotulo} líquido", brl(normais - estornos))


# --------------------------------------------------------------------------- #
# Exportação dos dados tratados
# --------------------------------------------------------------------------- #
def _df_para_csv(df: pd.DataFrame) -> bytes:
    """CSV amigável ao Excel brasileiro: UTF-8 com BOM, ';' e decimal ','."""
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%d/%m/%Y")
    return out.to_csv(index=False, sep=";", decimal=",", float_format="%.2f").encode("utf-8-sig")


df_para_csv = _df_para_csv  # nome público, usado pelas páginas


@st.cache_data(show_spinner="Gerando CSV tratado...")
def exportar_csv(base: str, mtime: float | None = None) -> bytes:
    """CSV da base já tratada (tipos convertidos, chaves de estorno corrigidas,
    colunas derivadas). `mtime` só invalida o cache quando o arquivo muda."""
    return _df_para_csv(carregar_base(base, mtime))


@st.cache_data(show_spinner="Gerando pacote ZIP...")
def exportar_zip(mtimes: tuple[float | None, ...]) -> bytes:
    """ZIP com os CSVs tratados das três bases."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for base, mtime in zip(ARQUIVOS, mtimes):
            z.writestr(nome_exportacao(base), exportar_csv(base, mtime))
    return buf.getvalue()


def nome_exportacao(base: str) -> str:
    return ARQUIVOS[base].replace(".csv", "_tratado.csv")


def mtime_de(base: str) -> float | None:
    p = caminho(base)
    return p.stat().st_mtime if p.exists() else None
