"""
Fonte de dados - Prefeitura de Centenário do Sul
==================================================
Página que lista cada PDF oficial exportado pelo sistema junto do seu CSV
correspondente, usado pelos apps de comparação (Liquidado x Pago /
Empenhado x Liquidado x Pago).

A correspondência é feita pelo nome do arquivo: o PDF
"pdf/<nome>.pdf" tem como par o CSV "data/<nome>.csv".
"""

import os

import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(BASE_DIR, "pdf")
DATA_DIR = os.path.join(BASE_DIR, "data")

st.title("📄 Fonte de dados")
st.caption(
    "Cada relatório abaixo é o PDF oficial exportado pelo sistema, junto do CSV "
    "correspondente que os apps usam para os cruzamentos."
)


def find_csv_for_pdf(pdf_filename: str):
    base = os.path.splitext(pdf_filename)[0]
    candidate = os.path.join(DATA_DIR, base + ".csv")
    return candidate if os.path.isfile(candidate) else None


if not os.path.isdir(PDF_DIR):
    st.error(f"Pasta de PDFs não encontrada: {PDF_DIR}")
    st.stop()

pdf_files = sorted(f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf"))

if not pdf_files:
    st.warning(f"Nenhum PDF encontrado em {PDF_DIR}")
    st.stop()

for pdf_name in pdf_files:
    pdf_path = os.path.join(PDF_DIR, pdf_name)
    csv_path = find_csv_for_pdf(pdf_name)

    st.subheader(pdf_name)
    col_pdf, col_csv = st.columns(2)

    with col_pdf:
        st.markdown("**PDF original**")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        st.download_button(
            "⬇️ Baixar PDF",
            data=pdf_bytes,
            file_name=pdf_name,
            mime="application/pdf",
            key=f"dl_pdf_{pdf_name}",
            width="stretch",
        )

    with col_csv:
        st.markdown("**CSV correspondente**")
        if csv_path is None:
            st.error("Nenhum CSV correspondente encontrado em data/.")
        else:
            st.caption(os.path.basename(csv_path))
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
            st.download_button(
                "⬇️ Baixar CSV",
                data=csv_bytes,
                file_name=os.path.basename(csv_path),
                mime="text/csv",
                key=f"dl_csv_{pdf_name}",
                width="stretch",
            )

    st.markdown("---")
