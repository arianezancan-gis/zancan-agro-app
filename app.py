import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

# 1. Configuração de acesso com o Google
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

def load_data():
    try:
        client = get_gspread_client()
        sheet = client.open("ZancanAgro").worksheet("CadastroAplicações")
        data = sheet.get_all_records()
        return sheet, pd.DataFrame(data)
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Drive: {e}")
        return None, pd.DataFrame()

# 2. Layout da Aplicação
st.set_page_config(page_title="ZancanAgro", layout="wide")
st.title("🌱 ZancanAgro - Sistema de Aplicações")

sheet, df_aplicacoes = load_data()

aba_cadastro, aba_historico = st.tabs(["📝 Cadastrar Aplicação", "📊 Histórico e Consulta"])

with aba_cadastro:
    st.subheader("Nova Aplicação no Campo")
    
    with st.form("form_aplicacao", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            produtor = st.text_input("Produtor", value="Mauricio")
            talhao = st.selectbox("Talhão", ["Postinho", "Mata-burro", "Macarrão", "Outro"])
            if talhao == "Outro":
                talhao = st.text_input("Nome do Talhão")
                
            tipo_aplicacao = st.selectbox(
                "Tipo de Aplicação", 
                ["Dessecação", "Plantio", "Limpa", "Fungicida 1", "Fungicida 2", "Adubação", "Outro"]
            )
            
        with col2:
            produto = st.text_input("Produto / Insumo")
            dose_ha = st.number_input("Dose/ha (L ou Kg)", min_value=0.0, step=0.01)
            area_ha = st.number_input("Área do Talhão (ha)", min_value=0.0, step=0.1)
            data_aplicacao = st.date_input("Data", value=date.today())
            
        volume_total = dose_ha * area_ha if area_ha > 0 else 0.0
        if volume_total > 0:
            st.info(f"💡 Volume Total Estimado: **{volume_total:.2f} L/Kg**")

        if st.form_submit_button("Salvar no Google Drive"):
            if not produto or dose_ha <= 0:
                st.error("Preencha o nome do produto e a dose!")
            elif sheet is None:
                st.error("Erro na conexão com o Google Drive.")
            else:
                nova_linha = [
                    produtor,
                    talhao,
                    tipo_aplicacao,
                    produto,
                    dose_ha,
                    volume_total,
                    data_aplicacao.strftime("%Y-%m-%d")
                ]
                sheet.append_row(nova_linha)
                st.success("✅ Salvo com sucesso na planilha do Google Drive!")
                st.rerun()

with aba_historico:
    st.subheader("Registros Salvos")
    if st.button("🔄 Atualizar Dados"):
        st.cache_resource.clear()
        st.rerun()

    if not df_aplicacoes.empty:
        st.dataframe(df_aplicacoes, use_container_width=True)
    else:
        st.info("Nenhum dado encontrado.")
