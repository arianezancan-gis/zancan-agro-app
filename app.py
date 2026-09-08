import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

# ---------------------------------------------------------
# 1. AUTENTICAÇÃO E CONEXÃO COM GOOGLE DRIVE
# ---------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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
    """Converte valores com vírgula ou ponto para float com segurança."""
    if pd.isna(val) or val == "" or str(val).strip() in ["#REF!", "#N/A", "None", "nan"]:
        return 0.0
    try:
        # Remove espaços e substitui vírgula decimal por ponto
        clean_val = str(val).replace(".", "").replace(",", ".").strip() if str(val).count(",") == 1 and str(val).count(".") == 1 else str(val).replace(",", ".").strip()
        return float(clean_val)
    except ValueError:
        return 0.0

@st.cache_data(ttl=30)
def load_all_data():
    try:
        client = get_gspread_client()
        spreadsheet = client.open("ZancanAgro")
        
        def get_df(sheet_name, fallback_index=0):
            try:
                ws = spreadsheet.worksheet(sheet_name)
            except Exception:
                ws = spreadsheet.get_worksheet(fallback_index)
            
            data = ws.get_all_records()
            df = pd.DataFrame(data)
            
            # Tratamento de decimais com vírgula em colunas numéricas
            for col in df.columns:
                df[col] = df[col].apply(lambda x: str(x).strip() if pd.notna(x) else x)
            
            return df.dropna(how="all")

        df_app = get_df("Aplicação", 0)
        df_talhao = get_df("Talhao", 1)
        df_produto = get_df("Produto", 2)
        df_produtor = get_df("Produtor", 3)
        df_tp = get_df("TpAplicação", 4)
        df_cultura = get_df("Cultura", 5)

        return (df_app, df_talhao, df_produto, df_produtor, df_tp, df_cultura)
    except Exception as e:
        st.error(f"Erro ao carregar dados do Google Drive: {e}")
        return [pd.DataFrame()] * 6

def get_worksheet_handle(sheet_name, fallback_index=0):
    client = get_gspread_client()
    spreadsheet = client.open("ZancanAgro")
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        return spreadsheet.get_worksheet(fallback_index)

# ---------------------------------------------------------
# 2. INTERFACE E CARREGAMENTO DE DADOS
# ---------------------------------------------------------
st.set_page_config(page_title="ZancanAgro - Gestão", layout="wide")
st.title("🌱 ZancanAgro - Lançamento de Aplicações")

(df_app, df_talhao, df_produto, df_produtor, df_tp, df_cultura) = load_all_data()

# Listas base
if not df_produtor.empty and "Nome" in df_produtor.columns:
    lista_produtores = sorted(df_produtor["Nome"].dropna().astype(str).str.strip().unique().tolist())
    lista_produtores = [p for p in lista_produtores if p]
else:
    lista_produtores = ["Mauricio"]

if not df_produto.empty and "Nome" in df_produto.columns:
    lista_produtos = sorted(df_produto["Nome"].dropna().astype(str).str.strip().unique().tolist())
    lista_produtos = [p for p in lista_produtos if p]
else:
    lista_produtos = []

if not df_tp.empty and "Nome" in df_tp.columns:
    lista_tipos = sorted(df_tp["Nome"].dropna().astype(str).str.strip().unique().tolist())
    lista_tipos = [t for t in lista_tipos if t]
else:
    lista_tipos = ["Dessecação", "Plantio", "Limpa", "Fungicida 1"]

aba_cadastro, aba_historico, aba_auxiliares = st.tabs(["📝 Cadastrar Aplicação", "📊 Histórico de Aplicações", "⚙️ Cadastros Auxiliares"])

# --- ABA 1: CADASTRO DE APLICAÇÕES ---
with aba_cadastro:
    st.subheader("Nova Aplicação de Insumos")
    
    col_prod, _ = st.columns([1, 2])
    with col_prod:
        produtor_sel = st.selectbox("1. Selecione o Produtor", options=lista_produtores, key="produtor_select")

    # Filtro de Talhões
    opcoes_talhao = []
    if not df_talhao.empty and "Produtor" in df_talhao.columns and "Nome da Área" in df_talhao.columns:
        df_talhao_filtrado = df_talhao[
            df_talhao["Produtor"].astype(str).str.strip().str.upper() == str(produtor_sel).strip().upper()
        ]
        opcoes_talhao = sorted(df_talhao_filtrado["Nome da Área"].dropna().astype(str).str.strip().unique().tolist())
        opcoes_talhao = [t for t in opcoes_talhao if t]

    col1, col2 = st.columns(2)
    
    with col1:
        talhao_sel = st.selectbox(
            "2. Talhão / Área", 
            options=opcoes_talhao if opcoes_talhao else ["Nenhum talhão cadastrado para este produtor"]
        )
        tipo_sel = st.selectbox("3. Tipo de Aplicação", options=lista_tipos)
        
    with col2:
        produto_sel = st.selectbox("4. Produto / Insumo", options=lista_produtos)
        dose_ha = st.number_input("5. Dose/ha (L ou Kg)", min_value=0.0, step=0.01, format="%.2f")
        data_aplicacao = st.date_input("6. Data da Aplicação", value=date.today())

    # Seleção da coluna de área baseada no Tipo de Aplicação
    coluna_area = "Área do Plantio" if str(tipo_sel).strip().lower() == "plantio" else "Área Pulverizada"

    # Cálculo reativo da área e do volume em tempo real com conversão correta de vírgula
    area_ha = 0.0
    if not df_talhao.empty and talhao_sel in opcoes_talhao:
        row_t = df_talhao[
            (df_talhao["Produtor"].astype(str).str.strip().str.upper() == str(produtor_sel).strip().upper()) & 
            (df_talhao["Nome da Área"].astype(str).str.strip().str.upper() == str(talhao_sel).strip().upper())
        ]
        if not row_t.empty and coluna_area in row_t.columns:
            area_ha = parse_float(row_t[coluna_area].values[0])

    volume_total = dose_ha * area_ha

    # Exibição do cálculo e indicação da área utilizada
    if dose_ha > 0 and area_ha > 0:
        st.info(f"🧪 **Volume Total Calculado:** **{volume_total:,.2f}** (L ou Kg)  *(Dose: {dose_ha} × {coluna_area}: {area_ha} ha)*")
    elif dose_ha > 0 and area_ha == 0:
        st.warning(f"⚠️ O talhão selecionado não possui o valor de **{coluna_area}** preenchido corretamente na aba Talhao.")

    st.write("")
    btn_salvar = st.button("💾 Salvar no Google Drive", type="primary")
    
    if btn_salvar:
        if not opcoes_talhao or talhao_sel not in opcoes_talhao:
            st.error("⚠️ Selecione um talhão válido associado ao produtor.")
        elif not produto_sel or dose_ha <= 0:
            st.error("⚠️ Selecione um produto e informe uma dose maior que zero.")
        else:
            with st.spinner("Gravando dados no Google Drive..."):
                try:
                    ws_app = get_worksheet_handle("Aplicação", 0)
                    
                    nova_linha = [
                        str(produtor_sel),
                        str(talhao_sel),
                        str(tipo_sel),
                        str(produto_sel),
                        str(dose_ha).replace(".", ","),
                        str(round(volume_total, 2)).replace(".", ",") if volume_total > 0 else "",
                        data_aplicacao.strftime("%d/%m/%Y")
                    ]
                    
                    ws_app.append_row(nova_linha, value_input_option="USER_ENTERED")
                    
                    st.cache_data.clear()
                    st.success("✅ Registro gravado com sucesso no Google Drive!")
                    st.rerun()
                except Exception as ex:
                    st.error(f"❌ Falha ao gravar no Google Drive: {ex}")

# --- ABA 2: HISTÓRICO DE APLICAÇÕES ---
with aba_historico:
    st.subheader("Registros Salvos no Google Drive")
    
    if st.button("🔄 Recarregar Dados"):
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
                if novo_prod_nome:
                    try:
                        ws_produto = get_worksheet_handle("Produto", 2)
                        proximo_codigo = len(df_produto) + 1
                        ws_produto.append_row([proximo_codigo, novo_prod_nome], value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"Produto '{novo_prod_nome}' cadastrado!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao salvar produto: {ex}")

    with col_b:
        st.markdown("### ➕ Novo Produtor")
        with st.form("form_novo_produtor"):
            novo_produtor_nome = st.text_input("Nome do Produtor")
            if st.form_submit_button("Cadastrar Produtor"):
                if novo_produtor_nome:
                    try:
                        ws_produtor = get_worksheet_handle("Produtor", 3)
                        proximo_codigo = len(df_produtor) + 1
                        ws_produtor.append_row([proximo_codigo, novo_produtor_nome], value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"Produtor '{novo_produtor_nome}' cadastrado!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao salvar produtor: {ex}")
