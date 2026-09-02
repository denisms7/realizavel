import streamlit as st

from utils import dados

st.title("⚙️ Fonte de Dados")
st.caption(
    "Os dados são lidos dos arquivos CSV exportados do SCP-550 fornecidos pelas Sysmar."
)

# ---------------------------------------------------------------- arquivos
st.subheader("Arquivos na pasta")
info = dados.info_arquivos()
st.dataframe(info, hide_index=True, width="stretch")

faltando = info[info["Encontrado"] == "❌"]["Arquivo"].tolist()
if faltando:
    st.error("Arquivo(s) não encontrado(s): " + ", ".join(faltando))

col1, col2 = st.columns([1, 5])
if col1.button("🔄 Recarregar", type="primary"):
    dados.limpar_cache()
    st.toast("Cache limpo. Os dados serão relidos do disco.")
    st.rerun()
col2.caption("O cache é invalidado automaticamente quando a data de modificação de um arquivo muda.")

# ---------------------------------------------------------------- carga
st.subheader("Resumo das bases")
bases = {}
for base in dados.ARQUIVOS:
    try:
        bases[base] = dados.carregar(base)
    except FileNotFoundError:
        continue

if not bases:
    st.stop()

cols = st.columns(len(bases))
for col, (base, df) in zip(cols, bases.items()):
    vcol = dados.COLUNAS_VALOR[base][0]
    with col:
        st.metric(base.capitalize(), f"{len(df):,}".replace(",", "."), help="Quantidade de linhas")
        st.write(f"**Total {vcol}:** {dados.brl(df[vcol].sum())}")
        dmin, dmax = df["DATA"].min(), df["DATA"].max()
        st.write(f"**Período:** {dmin:%d/%m/%Y} a {dmax:%d/%m/%Y}")
        st.write(f"**Exercícios:** {int(df['ANO'].min())} – {int(df['ANO'].max())}")

# ---------------------------------------------------------------- por exercício
st.subheader("Linhas por exercício")
import pandas as pd

cont = pd.DataFrame(
    {b.capitalize(): df["ANO"].value_counts() for b, df in bases.items()}
).sort_index().fillna(0).astype(int)
cont.index = cont.index.astype(str)
st.bar_chart(cont)

# ---------------------------------------------------------------- detalhe
st.subheader("Detalhe por base")
escolha = st.selectbox("Base", list(bases), format_func=str.capitalize)
df = bases[escolha]

aba_amostra, aba_qualidade, aba_tipos = st.tabs(["Amostra", "Qualidade dos dados", "Regras de tratamento"])

with aba_amostra:
    n = st.slider("Linhas exibidas", 10, 500, 50, step=10)
    st.dataframe(df.head(n), width="stretch")

with aba_qualidade:
    st.dataframe(dados.resumo_qualidade(df), hide_index=True, width="stretch")

with aba_tipos:
    st.markdown(
        f"""
- **Codificação / separador:** Latin-1, `;`.
- **Datas** (`{", ".join(dados.COLUNAS_DATA[escolha])}`): formato `dd.mm.aaaa`.
- **Valores** (`{", ".join(dados.COLUNAS_VALOR[escolha])}`): ponto decimal; valores entre parênteses são negativos.
- **Inteiros com ponto de milhar** (`{", ".join(dados.COLUNAS_INTEIRO[escolha])}`): `2.013` → `2013`.
- **Linhas com `;` dentro de um campo:** os pedaços excedentes são reagrupados na coluna `{dados.COLUNA_ABSORVE[escolha]}`.
- **Colunas derivadas:** `ANO` (extraído da chave `{dados.COLUNAS_CHAVE[escolha][0]}` = número/ano), `MES`,
  `FORNECEDOR_COD` e `FORNECEDOR_NOME` (separados de `FORNECEDORES`).
"""
        + (
            "- **Pagamentos:** `LIQUIDO` é recalculado como `VALOR_PAGO - RETENCOES`; `ESTORNO` indica linhas com `ESTORNO_PAGAMENTO` preenchido."
            if escolha == "pagamentos"
            else ""
        )
    )
