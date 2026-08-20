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

ROW_COLS = [4, 1, 1]

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

header_name, header_pdf, header_csv = st.columns(ROW_COLS, vertical_alignment="center")
header_name.markdown("**Relatório**")
header_pdf.markdown("**PDF**")
header_csv.markdown("**CSV**")
st.divider()

for pdf_name in pdf_files:
    pdf_path = os.path.join(PDF_DIR, pdf_name)
    csv_path = find_csv_for_pdf(pdf_name)

    col_name, col_pdf, col_csv = st.columns(ROW_COLS, vertical_alignment="center")

    with col_name:
        st.write(pdf_name)

    with col_pdf:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        st.download_button(
            "⬇️ PDF",
            data=pdf_bytes,
            file_name=pdf_name,
            mime="application/pdf",
            key=f"dl_pdf_{pdf_name}",
            help=f"{size_mb:.1f} MB",
            width="stretch",
        )

    with col_csv:
        if csv_path is None:
            st.caption("CSV não encontrado")
        else:
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
            st.download_button(
                "⬇️ CSV",
                data=csv_bytes,
                file_name=os.path.basename(csv_path),
                mime="text/csv",
                key=f"dl_csv_{pdf_name}",
                help=os.path.basename(csv_path),
                width="stretch",
            )

    st.divider()
