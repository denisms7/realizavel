import pandas as pd
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
        dados.texto(f"**Total {vcol}:** {dados.brl(df[vcol].sum())}")
        dmin, dmax = df["DATA"].min(), df["DATA"].max()
        if pd.notna(dmin) and pd.notna(dmax):
            st.write(f"**Período:** {dmin:%d/%m/%Y} a {dmax:%d/%m/%Y}")
        st.write(f"**Exercícios:** {int(df['ANO'].min())} – {int(df['ANO'].max())}")

# ---------------------------------------------------------------- por exercício
st.subheader("Linhas por exercício")

cont = pd.DataFrame(
    {b.capitalize(): df["ANO"].value_counts() for b, df in bases.items()}
).sort_index().fillna(0).astype(int)
cont.index = cont.index.astype(str)
st.bar_chart(cont)

# ---------------------------------------------------------------- exportação
st.subheader("Exportar dados tratados")
st.caption(
    "CSVs com os tipos já convertidos (datas, valores, inteiros), chaves de estorno corrigidas e colunas derivadas "
    "(`ANO`, `MES`, `ESTORNO`, `FORNECEDOR_COD/NOME`, `LIQUIDO`…). Formato: UTF-8, separador `;`, decimal `,` — abre direto no Excel."
)
cols_exp = st.columns(len(bases) + 1)
for col, base in zip(cols_exp, bases):
    col.download_button(
        f"⬇️ {base.capitalize()}",
        dados.exportar_csv(base, dados.mtime_de(base)),
        dados.nome_exportacao(base),
        "text/csv",
        key=f"exp_{base}",
        width="stretch",
    )
if len(bases) == len(dados.ARQUIVOS):
    cols_exp[-1].download_button(
        "📦 Todas (ZIP)",
        dados.exportar_zip(tuple(dados.mtime_de(b) for b in dados.ARQUIVOS)),
        "scp550_tratado.zip",
        "application/zip",
        key="exp_zip",
        width="stretch",
    )

# ---------------------------------------------------------------- detalhe
st.subheader("Detalhe por base")
escolha = st.selectbox("Base", list(bases), format_func=str.capitalize, help="Escolhe qual das três bases aparece nas abas abaixo (amostra, qualidade e regras). Não afeta as outras páginas.")
df = bases[escolha]

aba_amostra, aba_qualidade, aba_tipos = st.tabs(["Amostra", "Qualidade dos dados", "Regras de tratamento"])

with aba_amostra:
    n = st.slider("Linhas exibidas", 10, 500, 50, step=10, help="Quantidade de linhas iniciais da base tratada mostradas na amostra. Só limita a exibição; não filtra dados.")
    st.dataframe(df.head(n), width="stretch")

with aba_qualidade:
    st.dataframe(dados.resumo_qualidade(df), hide_index=True, width="stretch")

with aba_tipos:
    st.markdown(
        f"""
- **Codificação / separador:** Latin-1, `;`.
- **Datas** (`{", ".join(dados.COLUNAS_DATA[escolha])}`): formato `dd.mm.aaaa`.
- **Valores** (`{", ".join(dados.COLUNAS_VALOR[escolha])}`): ponto decimal; valores entre parênteses são negativos.
- **Valor negativo = estorno** do lançamento original (anulação de empenho, estorno de liquidação/pagamento); gera as colunas `ESTORNO` e `LANCAMENTO`.
- **Chave dos estornos:** em Empenhos e Liquidações, na linha de estorno a coluna `EMPENHO`/`LIQUIDACAO` traz o número do próprio estorno;
  o lançamento original está em `NUMERO.../EXERCICIO...`. A chave é regravada para apontar ao original e o número do estorno fica em `EMPENHO_ESTORNO`/`LIQUIDACAO_ESTORNO`.
- **Inteiros com ponto de milhar** (`{", ".join(dados.COLUNAS_INTEIRO[escolha])}`): `2.013` → `2013`.
- **Linhas com `;` dentro de um campo:** os pedaços excedentes são reagrupados em uma das colunas `{', '.join(dados.COLUNAS_ABSORVEM[escolha])}`, escolhendo a hipótese em que datas e valores voltam a ser válidos.
- **Colunas derivadas:** `ANO` (extraído da chave `{dados.COLUNAS_CHAVE[escolha][0]}` = número/ano), `MES`,
  `FORNECEDOR_COD` e `FORNECEDOR_NOME` (separados de `FORNECEDORES`).
"""
        + (
            "- **Pagamentos:** `LIQUIDO` é recalculado como `VALOR_PAGO - RETENCOES`; nos pagamentos o valor negativo coincide com `ESTORNO_PAGAMENTO` preenchido."
            if escolha == "pagamentos"
            else ""
        )
    )
