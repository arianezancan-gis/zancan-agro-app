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
    """Converte com segurança qualquer texto com vírgula ou ponto para float."""
    if pd.isna(val) or val is None:
        return 0.0
    
    s = str(val).strip()
    if not s or s in ["#REF!", "#N/A", "None", "nan", "NULL"]:
        return 0.0

    try:
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        elif "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except ValueError:
        return 0.0

@st.cache_data(ttl=30)
def load_all_data():
    try:
        client = get_gspread_client()
        spreadsheet = client.open("ZancanAgro")
        
        def get_df_raw(sheet_name, fallback_index=0):
            try:
                ws = spreadsheet.worksheet(sheet_name)
            except Exception:
                ws = spreadsheet.get_worksheet(fallback_index)
            
            rows = ws.get_all_values()
            if not rows:
                return pd.DataFrame()
            
            headers = [str(h).strip() for h in rows[0]]
            data = rows[1:]
            df = pd.DataFrame(data, columns=headers)
            
            for col in df.columns:
                df[col] = df[col].astype(str).str.strip()
                
            return df.dropna(how="all")

        df_app = get_df_raw("Aplicação", 0)
        df_talhao = get_df_raw("Talhao", 1)
        df_produto = get_df_raw("Produto", 2)
        df_produtor = get_df_raw("Produtor", 3)
        df_tp = get_df_raw("TpAplicação", 4)
        df_cultura = get_df_raw("Cultura", 5)

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

# Inicialização segura dos estados de sessão
if "dose_input" not in st.session_state:
    st.session_state.dose_input = 0.0

if "msg_sucesso" not in st.session_state:
    st.session_state.msg_sucesso = ""

# Listas base
if not df_produtor.empty and "Nome" in df_produtor.columns:
    lista_produtores = sorted(df_produtor["Nome"].dropna().unique().tolist())
    lista_produtores = [p for p in lista_produtores if p]
else:
    lista_produtores = ["Mauricio"]

if not df_produto.empty and "Nome" in df_produto.columns:
    lista_produtos = sorted(df_produto["Nome"].dropna().unique().tolist())
    lista_produtos = [p for p in lista_produtos if p]
else:
    lista_produtos = []

if not df_tp.empty and "Nome" in df_tp.columns:
    lista_tipos = sorted(df_tp["Nome"].dropna().unique().tolist())
    lista_tipos = [t for t in lista_tipos if t]
else:
    lista_tipos = ["Dessecação", "Plantio", "Limpa", "Fungicida 1"]

if not df_cultura.empty and "Nome" in df_cultura.columns:
    lista_culturas = sorted(df_cultura["Nome"].dropna().unique().tolist())
    lista_culturas = [c for c in lista_culturas if c]
else:
    lista_culturas = ["Soja", "Milho", "Trigo"]

aba_cadastro, aba_historico, aba_auxiliares = st.tabs(["📝 Cadastrar Aplicação", "📊 Histórico de Aplicações", "⚙️ Cadastros Auxiliares"])

# --- ABA 1: CADASTRO DE APLICAÇÕES ---
with aba_cadastro:
    st.subheader("Nova Aplicação de Insumos")
    
    # Exibe a mensagem de sucesso caso exista no estado da sessão
    if st.session_state.msg_sucesso:
        st.success(st.session_state.msg_sucesso)
        st.session_state.msg_sucesso = ""

    col_prod, _ = st.columns([1, 2])
    with col_prod:
        produtor_sel = st.selectbox("1. Selecione o Produtor", options=lista_produtores, key="produtor_select")

    opcoes_talhao = []
    if not df_talhao.empty and "Produtor" in df_talhao.columns and "Nome da Área" in df_talhao.columns:
        df_talhao_filtrado = df_talhao[
            df_talhao["Produtor"].str.upper() == str(produtor_sel).upper()
        ]
        opcoes_talhao = sorted(df_talhao_filtrado["Nome da Área"].dropna().unique().tolist())
        opcoes_talhao = [t for t in opcoes_talhao if t]

    col1, col2 = st.columns(2)
    
    with col1:
        talhao_sel = st.selectbox(
            "2. Talhão / Área", 
            options=opcoes_talhao if opcoes_talhao else ["Nenhum talhão cadastrado para este produtor"],
            key="talhao_select"
        )
        tipo_sel = st.selectbox("3. Tipo de Aplicação", options=lista_tipos, key="tipo_select")
        
    with col2:
        produto_sel = st.selectbox("4. Produto / Insumo", options=lista_produtos, key="produto_select")
        dose_ha = st.number_input("5. Dose/ha (L ou Kg)", min_value=0.0, step=0.01, format="%.2f", key="dose_input")
        data_aplicacao = st.date_input("6. Data da Aplicação", value=date.today(), key="data_select")

    coluna_area = "Área do Plantio" if str(tipo_sel).strip().lower() == "plantio" else "Área Pulverizada"

    area_ha = 0.0
    valor_area_bruto = "0"
    if not df_talhao.empty and talhao_sel in opcoes_talhao:
        row_t = df_talhao[
            (df_talhao["Produtor"].str.upper() == str(produtor_sel).upper()) & 
            (df_talhao["Nome da Área"].str.upper() == str(talhao_sel).upper())
        ]
        if not row_t.empty and coluna_area in row_t.columns:
            valor_area_bruto = row_t[coluna_area].values[0]
            area_ha = parse_float(valor_area_bruto)

    volume_total = dose_ha * area_ha

    if dose_ha > 0 and area_ha > 0:
        st.info(f"🧪 **Volume Total Calculado:** **{volume_total:,.2f}** (L ou Kg)  *(Dose: {dose_ha} × {coluna_area}: {area_ha} ha)*")
    elif dose_ha > 0 and area_ha == 0:
        st.warning(f"⚠️ O valor lido para **{coluna_area}** foi `{valor_area_bruto}`. Verifique o cadastro do talhão.")

    st.write("")
    
    # Função para processar a gravação no Google Drive
    def gravar_aplicacao():
        if not opcoes_talhao or talhao_sel not in opcoes_talhao:
            st.error("⚠️ Selecione um talhão válido associado ao produtor.")
        elif not produto_sel or dose_ha <= 0:
            st.error("⚠️ Selecione um produto e informe uma dose maior que zero.")
        else:
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
                
                # Zera o campo de dose com segurança antes da atualização da página
                st.session_state.dose_input = 0.0
                st.session_state.msg_sucesso = "✅ Aplicação registrada com sucesso no Google Drive!"
                st.cache_data.clear()
            except Exception as ex:
                st.error(f"❌ Falha ao gravar no Google Drive: {ex}")

    st.button("💾 Salvar no Google Drive", type="primary", on_click=gravar_aplicacao)

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
    st.subheader("⚙️ Cadastros do Sistema")
    
    sub_tab1, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs([
        "📍 Novo Talhão", 
        "🌾 Nova Cultura", 
        "📋 Novo Tipo de Aplicação", 
        "📦 Novo Insumo/Produto", 
        "👤 Novo Produtor"
    ])
    
    # 1. CADASTRO DE TALHÃO
    with sub_tab1:
        st.markdown("### Cadastrar Novo Talhão / Área")
        with st.form("form_novo_talhao", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                t_produtor = st.selectbox("Produtor", options=lista_produtores)
                t_nome = st.text_input("Nome da Área / Talhão (ex: Gleba 01)")
                t_cultura = st.selectbox("Cultura Inicial", options=lista_culturas)
            with c2:
                t_area_real = st.number_input("Área Real (ha)", min_value=0.0, step=0.1, format="%.2f")
                t_area_plantio = st.number_input("Área do Plantio (ha)", min_value=0.0, step=0.1, format="%.2f")
                t_area_pulv = st.number_input("Área Pulverizada (ha)", min_value=0.0, step=0.1, format="%.2f")
                t_area_disp = st.number_input("Área Dispersão (ha)", min_value=0.0, step=0.1, format="%.2f")
            
            btn_cad_talhao = st.form_submit_button("Salvar Talhão no Google Drive")
            if btn_cad_talhao:
                if t_nome.strip():
                    try:
                        ws_talhao = get_worksheet_handle("Talhao", 1)
                        prox_codigo = len(df_talhao) + 1
                        nova_linha_t = [
                            prox_codigo,
                            t_produtor,
                            t_nome.strip(),
                            t_cultura,
                            str(t_area_real).replace(".", ","),
                            str(t_area_plantio).replace(".", ","),
                            str(t_area_pulv).replace(".", ","),
                            str(t_area_disp).replace(".", ",")
                        ]
                        ws_talhao.append_row(nova_linha_t, value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"✅ Talhão '{t_nome}' cadastrado com sucesso!")
                    except Exception as ex:
                        st.error(f"Erro ao cadastrar talhão: {ex}")
                else:
                    st.warning("Informe o nome do talhão.")

    # 2. CADASTRO DE CULTURA
    with sub_tab2:
        st.markdown("### Cadastrar Nova Cultura")
        with st.form("form_nova_cultura", clear_on_submit=True):
            c_nome = st.text_input("Nome da Cultura (ex: Algodão, Feijão)")
            btn_cad_cultura = st.form_submit_button("Salvar Cultura")
            if btn_cad_cultura:
                if c_nome.strip():
                    try:
                        ws_cultura = get_worksheet_handle("Cultura", 5)
                        prox_codigo = len(df_cultura) + 1
                        ws_cultura.append_row([prox_codigo, c_nome.strip()], value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"✅ Cultura '{c_nome}' cadastrada com sucesso!")
                    except Exception as ex:
                        st.error(f"Erro ao cadastrar cultura: {ex}")
                else:
                    st.warning("Informe o nome da cultura.")

    # 3. CADASTRO DE TIPO DE APLICAÇÃO
    with sub_tab3:
        st.markdown("### Cadastrar Novo Tipo de Aplicação")
        with st.form("form_novo_tp", clear_on_submit=True):
            tp_nome = st.text_input("Nome do Tipo de Aplicação (ex: Foliar, Adubação de Cobertura)")
            btn_cad_tp = st.form_submit_button("Salvar Tipo de Aplicação")
            if btn_cad_tp:
                if tp_nome.strip():
                    try:
                        ws_tp = get_worksheet_handle("TpAplicação", 4)
                        prox_codigo = len(df_tp) + 1
                        ws_tp.append_row([prox_codigo, tp_nome.strip()], value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"✅ Tipo de Aplicação '{tp_nome}' cadastrado com sucesso!")
                    except Exception as ex:
                        st.error(f"Erro ao cadastrar tipo de aplicação: {ex}")
                else:
                    st.warning("Informe o nome do tipo de aplicação.")

    # 4. CADASTRO DE PRODUTO
    with sub_tab4:
        st.markdown("### Cadastrar Novo Produto / Insumo")
        with st.form("form_novo_prod", clear_on_submit=True):
            novo_prod_nome = st.text_input("Nome do Produto")
            if st.form_submit_button("Cadastrar Produto"):
                if novo_prod_nome.strip():
                    try:
                        ws_produto = get_worksheet_handle("Produto", 2)
                        proximo_codigo = len(df_produto) + 1
                        ws_produto.append_row([proximo_codigo, novo_prod_nome.strip()], value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"✅ Produto '{novo_prod_nome}' cadastrado com sucesso!")
                    except Exception as ex:
                        st.error(f"Erro ao salvar produto: {ex}")
                else:
                    st.warning("Informe o nome do produto.")

    # 5. CADASTRO DE PRODUTOR
    with sub_tab5:
        st.markdown("### Cadastrar Novo Produtor")
        with st.form("form_novo_produtor", clear_on_submit=True):
            novo_produtor_nome = st.text_input("Nome do Produtor")
            if st.form_submit_button("Cadastrar Produtor"):
                if novo_produtor_nome.strip():
                    try:
                        ws_produtor = get_worksheet_handle("Produtor", 3)
                        proximo_codigo = len(df_produtor) + 1
                        ws_produtor.append_row([proximo_codigo, novo_produtor_nome.strip()], value_input_option="USER_ENTERED")
                        st.cache_data.clear()
                        st.success(f"✅ Produtor '{novo_produtor_nome}' cadastrado com sucesso!")
                    except Exception as ex:
                        st.error(f"Erro ao salvar produtor: {ex}")
                else:
                    st.warning("Informe o nome do produtor.")
