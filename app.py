import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

# ---------------------------------------------------------
# 1. AUTENTICAÇÃO COM GOOGLE DRIVE
# ---------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_gspread_client():
    service_account_info = dict(st.secrets["gcp_service_account"])
    if "private_key" in service_account_info:
        service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")

    credentials = Credentials.from_service_account_info(
        service_account_info, 
        scopes=SCOPES
    )
    return gspread.authorize(credentials)

def parse_float(val):
    if pd.isna(val) or val == "" or str(val).strip() == "#REF!":
        return 0.0
    try:
        return float(str(val).replace(",", ".").strip())
    except ValueError:
        return 0.0

@st.cache_data(ttl=60)
def load_all_data():
    try:
        client = get_gspread_client()
        spreadsheet = client.open("ZancanAgro")
        
        def get_ws_and_df(sheet_name, fallback_index=0):
            try:
                ws = spreadsheet.worksheet(sheet_name)
            except Exception:
                ws = spreadsheet.get_worksheet(fallback_index)
            data = ws.get_all_records()
            return ws, pd.DataFrame(data)

        ws_app, df_app = get_ws_and_df("Aplicação", 0)
        ws_talhao, df_talhao = get_ws_and_df("Talhao", 1)
        ws_produto, df_produto = get_ws_and_df("Produto", 2)
        ws_produtor, df_produtor = get_ws_and_df("Produtor", 3)
        ws_tp, df_tp = get_ws_and_df("TpAplicação", 4)
        ws_cultura, df_cultura = get_ws_and_df("Cultura", 5)

        return (ws_app, df_app, ws_talhao, df_talhao, ws_produto, df_produto, 
                ws_produtor, df_produtor, ws_tp, df_tp, ws_cultura, df_cultura)
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Drive: {e}")
        return [None, pd.DataFrame()] * 6

# ---------------------------------------------------------
# 2. INTERFACE E CARREGAMENTO DE DADOS
# ---------------------------------------------------------
st.set_page_config(page_title="ZancanAgro - Sistema de Gestão", layout="wide")
st.title("🌱 ZancanAgro - Lançamento de Aplicações")

(ws_app, df_app, ws_talhao, df_talhao, ws_produto, df_produto, 
 ws_produtor, df_produtor, ws_tp, df_tp, ws_cultura, df_cultura) = load_all_data()

# Tratamento e preparação de listas auxiliares
lista_produtores = sorted(df_produtor["Nome"].dropna().astype(str).unique()) if not df_produtor.empty else ["Mauricio"]
lista_produtos = sorted(df_produto["Nome"].dropna().astype(str).unique()) if not df_produto.empty else []
lista_tipos = sorted(df_tp["Nome"].dropna().astype(str).unique()) if not df_tp.empty else ["Dessecação", "Plantio", "Limpa", "Fungicida 1"]

aba_cadastro, aba_historico, aba_auxiliares = st.tabs(["📝 Cadastrar Aplicação", "📊 Histórico de Aplicações", "⚙️ Cadastros Auxiliares"])

# --- ABA 1: CADASTRO DE APLICAÇÕES ---
with aba_cadastro:
    st.subheader("Nova Aplicação de Insumos")
    
    with st.form("form_aplicacao", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            produtor_sel = st.selectbox("Produtor", options=lista_produtores)
            
            # Filtra os talhões pertencentes ao produtor selecionado
            if not df_talhao.empty and "Produtor" in df_talhao.columns:
                df_talhao_prod = df_talhao[df_talhao["Produtor"].astype(str) == str(produtor_sel)]
                opcoes_talhao = df_talhao_prod["Nome da Área"].dropna().astype(str).unique().tolist()
            else:
                opcoes_talhao = []
                
            talhao_sel = st.selectbox("Talhão / Área", options=opcoes_talhao if opcoes_talhao else ["Padrão"])
            
            tipo_sel = st.selectbox("Tipo de Aplicação", options=lista_tipos)
            
        with col2:
            produto_sel = st.selectbox("Produto / Insumo", options=lista_produtos)
            dose_ha = st.number_input("Dose/ha (L ou Kg)", min_value=0.0, step=0.01, format="%.2f")
            
            # Busca a Área Pulverizada cadastrada para o Talhão
            area_pulverizada = 0.0
            if not df_talhao.empty and talhao_sel in opcoes_talhao:
                row_t = df_talhao[(df_talhao["Produtor"].astype(str) == str(produtor_sel)) & 
                                 (df_talhao["Nome da Área"].astype(str) == str(talhao_sel))]
                if not row_t.empty and "Área Pulverizada" in row_t.columns:
                    area_pulverizada = parse_float(row_t["Área Pulverizada"].values[0])

            area_ha = st.number_input("Área Pulverizada (ha)", value=area_pulverizada, min_value=0.0, step=0.1)
            data_aplicacao = st.date_input("Data da Aplicação", value=date.today())

        # Cálculo do Volume Total
        volume_total = dose_ha * area_ha
        if volume_total > 0:
            st.info(f"💡 **Volume Total Estimado:** {volume_total:.2f} (L ou Kg)")

        btn_salvar = st.form_submit_button("Salvar no Google Drive")
        
        if btn_salvar:
            if not produto_sel or dose_ha <= 0:
                st.error("Selecione um produto e preencha uma dose maior que zero.")
            elif ws_app is None:
                st.error("Erro na conexão com a planilha no Google Drive.")
            else:
                # Formata linha no padrão da aba Aplicação
                nova_linha = [
                    produtor_sel,
                    talhao_sel,
                    tipo_sel,
                    produto_sel,
                    str(dose_ha).replace(".", ","),
                    str(round(volume_total, 2)).replace(".", ",") if volume_total > 0 else "",
                    data_aplicacao.strftime("%d/%m/%Y")
                ]
                
                ws_app.append_row(nova_linha)
                st.success("✅ Aplicação registrada com sucesso!")
                st.cache_data.clear()
                st.rerun()

# --- ABA 2: HISTÓRICO DE APLICAÇÕES ---
with aba_historico:
    st.subheader("Registros Salvos no Google Drive")
    
    if st.button("🔄 Atualizar Tabela"):
        st.cache_data.clear()
        st.rerun()

    if not df_app.empty:
        st.dataframe(df_app, use_container_width=True)
    else:
        st.info("Nenhuma aplicação cadastrada até o momento.")

# --- ABA 3: CADASTROS AUXILIARES ---
with aba_auxiliares:
    st.subheader("Adicionar Novos Insumos ou Produtores")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("### ➕ Novo Produto")
        with st.form("form_novo_prod"):
            novo_prod_nome = st.text_input("Nome do Produto")
            if st.form_submit_button("Cadastrar Produto"):
                if novo_prod_nome and ws_produto:
                    proximo_codigo = len(df_produto) + 1
                    ws_produto.append_row([proximo_codigo, novo_prod_nome])
                    st.success(f"Produto '{novo_prod_nome}' cadastrado!")
                    st.cache_data.clear()
                    st.rerun()

    with col_b:
        st.markdown("### ➕ Novo Produtor")
        with st.form("form_novo_produtor"):
            novo_produtor_nome = st.text_input("Nome do Produtor")
            if st.form_submit_button("Cadastrar Produtor"):
                if novo_produtor_nome and ws_produtor:
                    proximo_codigo = len(df_produtor) + 1
                    ws_produtor.append_row([proximo_codigo, novo_produtor_nome])
                    st.success(f"Produtor '{novo_produtor_nome}' cadastrado!")
                    st.cache_data.clear()
                    st.rerun()
