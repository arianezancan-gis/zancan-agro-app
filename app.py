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

def atualizar_linha_gspread(sheet_name, fallback_index, num_linha_planilha, nova_linha):
    ws = get_worksheet_handle(sheet_name, fallback_index)
    col_final = chr(ord('A') + len(nova_linha) - 1)
    cell_range = f"A{num_linha_planilha}:{col_final}{num_linha_planilha}"
    ws.update(cell_range, [nova_linha], value_input_option="USER_ENTERED")

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

# Definição das abas da aplicação
aba_dashboard, aba_cadastro, aba_historico, aba_auxiliares, aba_edicao_aux = st.tabs([
    "📈 Dashboard & Resumos",
    "📝 Cadastrar Aplicação", 
    "📊 Histórico de Aplicações", 
    "⚙️ Cadastros Auxiliares",
    "✏️ Editar Cadastros Auxiliares"
])

# --- ABA DASHBOARD & RESUMOS ---
with aba_dashboard:
    st.subheader("📊 Resumo e Métricas das Aplicações")
    
    if df_app.empty:
        st.info("Nenhum dado de aplicação cadastrado para exibir o dashboard.")
    else:
        # Copia e prepara o DataFrame para análise
        df_dash = df_app.copy()
        
        # Identificação inteligente de colunas
        cols_lower = {col.lower(): col for col in df_dash.columns}
        col_produtor = cols_lower.get("produtor", df_dash.columns[0])
        col_talhao = cols_lower.get("talhão / área", cols_lower.get("talhao", cols_lower.get("talhão", df_dash.columns[1])))
        col_tipo = cols_lower.get("tipo de aplicação", cols_lower.get("tipo", df_dash.columns[2]))
        col_produto = cols_lower.get("produto / insumo", cols_lower.get("produto", df_dash.columns[3]))
        col_dose = cols_lower.get("dose/ha (l ou kg)", cols_lower.get("dose/ha", cols_lower.get("dose", df_dash.columns[4])))
        col_vol = cols_lower.get("volume total (l ou kg)", cols_lower.get("volume total", cols_lower.get("volume", df_dash.columns[5] if len(df_dash.columns) > 5 else df_dash.columns[-1])))

        # Conversão dos números de volume e dose
        df_dash["Volume_Num"] = df_dash[col_vol].apply(parse_float)
        df_dash["Dose_Num"] = df_dash[col_dose].apply(parse_float)

        # Filtros de Dashboard
        st.markdown("#### 🔍 Filtros")
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            prods_disponiveis = ["Todos"] + sorted(df_dash[col_produtor].dropna().unique().tolist())
            filtro_produtor = st.selectbox("Filtrar por Produtor:", options=prods_disponiveis)
        
        with f_col2:
            produtos_disponiveis = ["Todos"] + sorted(df_dash[col_produto].dropna().unique().tolist())
            filtro_produto = st.selectbox("Filtrar por Produto:", options=produtos_disponiveis)

        # Aplicação dos filtros
        df_filtrado = df_dash.copy()
        if filtro_produtor != "Todos":
            df_filtrado = df_filtrado[df_filtrado[col_produtor] == filtro_produtor]
        if filtro_produto != "Todos":
            df_filtrado = df_filtrado[df_filtrado[col_produto] == filtro_produto]

        st.markdown("---")

        # 1. Cartões de Métricas Chave (KPIs)
        total_volume = df_filtrado["Volume_Num"].sum()
        total_aplicacoes = len(df_filtrado)
        total_areas = df_filtrado[col_talhao].nunique()

        m1, m2, m3 = st.columns(3)
        m1.metric("📦 Volume Total Aplicado", f"{total_volume:,.2f} L/Kg")
        m2.metric("📋 Total de Aplicações", f"{total_aplicacoes}")
        m3.metric("📍 Áreas / Talhões Atendidos", f"{total_areas}")

        st.markdown("---")

        # 2. Resumos em Tabelas e Gráficos
        g_col1, g_col2 = st.columns(2)

        with g_col1:
            st.markdown("### 📍 Total Aplicado por Área / Talhão")
            resumo_area = df_filtrado.groupby(col_talhao)["Volume_Num"].sum().reset_index()
            resumo_area.columns = ["Área / Talhão", "Volume Total (L/Kg)"]
            resumo_area = resumo_area.sort_values(by="Volume Total (L/Kg)", ascending=False)
            
            # Exibe Tabela formatada
            st.dataframe(
                resumo_area.style.format({"Volume Total (L/Kg)": "{:,.2f}"}),
                use_container_width=True,
                hide_index=True
            )

            # Gráfico de barras
            st.bar_chart(resumo_area.set_index("Área / Talhão"))

        with g_col2:
            st.markdown("### 📦 Total de Insumos Aplicados")
            resumo_prod = df_filtrado.groupby(col_produto)["Volume_Num"].sum().reset_index()
            resumo_prod.columns = ["Produto / Insumo", "Volume Total (L/Kg)"]
            resumo_prod = resumo_prod.sort_values(by="Volume Total (L/Kg)", ascending=False)

            # Exibe Tabela formatada
            st.dataframe(
                resumo_prod.style.format({"Volume Total (L/Kg)": "{:,.2f}"}),
                use_container_width=True,
                hide_index=True
            )

            # Gráfico de barras
            st.bar_chart(resumo_prod.set_index("Produto / Insumo"))

        st.markdown("---")

        # 3. Cruzamento Detalhado: Produto x Área
        st.markdown("### 📑 Detalhamento: Quanto de cada produto foi aplicado em cada Área")
        pivot_area_prod = pd.pivot_table(
            df_filtrado,
            values="Volume_Num",
            index=[col_talhao],
            columns=[col_produto],
            aggfunc="sum",
            fill_value=0.0
        )
        
        st.dataframe(
            pivot_area_prod.style.format("{:,.2f}"),
            use_container_width=True
        )

# --- ABA 1: CADASTRO DE APLICAÇÕES ---
with aba_cadastro:
    st.subheader("Nova Aplicação de Insumos")
    
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

# --- ABA 4: EDIÇÃO DE CADASTROS AUXILIARES ---
with aba_edicao_aux:
    st.subheader("✏️ Editar Registros Auxiliares")
    
    ed_tab1, ed_tab2, ed_tab3, ed_tab4, ed_tab5 = st.tabs([
        "📍 Editar Talhão", 
        "🌾 Editar Cultura", 
        "📋 Editar Tipo de Aplicação", 
        "📦 Editar Insumo/Produto", 
        "👤 Editar Produtor"
    ])
    
    # 1. EDIÇÃO DE TALHÃO
    with ed_tab1:
        st.markdown("### Editar Talhão")
        if df_talhao.empty:
            st.info("Nenhum talhão cadastrado para editar.")
        else:
            options_talhoes = []
            for idx, r in df_talhao.iterrows():
                options_talhoes.append((f"{r.get('Produtor', '')} - {r.get('Nome da Área', '')} (Cód: {r.get('Código', '')})", idx + 2, r))
            
            sel_talhao_opt = st.selectbox(
                "Selecione o Talhão para Editar:", 
                options=[opt[0] for opt in options_talhoes],
                key="edit_talhao_select"
            )
            
            sel_tuple = [opt for opt in options_talhoes if opt[0] == sel_talhao_opt][0]
            row_idx_sheet = sel_tuple[1]
            dados = sel_tuple[2]

            with st.form("form_edit_talhao"):
                col1, col2 = st.columns(2)
                with col1:
                    e_codigo = st.text_input("Código", value=str(dados.get("Código", "")), disabled=True)
                    e_produtor = st.selectbox("Produtor", options=lista_produtores, index=lista_produtores.index(dados.get("Produtor", "")) if dados.get("Produtor", "") in lista_produtores else 0)
                    e_nome = st.text_input("Nome da Área / Talhão", value=str(dados.get("Nome da Área", "")))
                    e_cultura = st.selectbox("Cultura Inicial", options=lista_culturas, index=lista_culturas.index(dados.get("Cultura Inicial", "")) if dados.get("Cultura Inicial", "") in lista_culturas else 0)
                with col2:
                    e_area_real = st.number_input("Área Real (ha)", value=parse_float(dados.get("Área Real", 0)), step=0.1, format="%.2f")
                    e_area_plantio = st.number_input("Área do Plantio (ha)", value=parse_float(dados.get("Área do Plantio", 0)), step=0.1, format="%.2f")
                    e_area_pulv = st.number_input("Área Pulverizada (ha)", value=parse_float(dados.get("Área Pulverizada", 0)), step=0.1, format="%.2f")
                    e_area_disp = st.number_input("Área Dispersão (ha)", value=parse_float(dados.get("Área Dispersão", 0)), step=0.1, format="%.2f")
                
                if st.form_submit_button("Atualizar Talhão no Google Drive"):
                    try:
                        nova_linha = [
                            str(e_codigo),
                            str(e_produtor),
                            str(e_nome).strip(),
                            str(e_cultura),
                            str(e_area_real).replace(".", ","),
                            str(e_area_plantio).replace(".", ","),
                            str(e_area_pulv).replace(".", ","),
                            str(e_area_disp).replace(".", ",")
                        ]
                        atualizar_linha_gspread("Talhao", 1, row_idx_sheet, nova_linha)
                        st.cache_data.clear()
                        st.success("✅ Talhão atualizado com sucesso!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao atualizar talhão: {ex}")

    # 2. EDIÇÃO DE CULTURA
    with ed_tab2:
        st.markdown("### Editar Cultura")
        if df_cultura.empty:
            st.info("Nenhuma cultura cadastrada para editar.")
        else:
            opts_c = [(f"{r.get('Nome', '')} (Cód: {r.get('Código', '')})", idx + 2, r) for idx, r in df_cultura.iterrows()]
            sel_c_opt = st.selectbox("Selecione a Cultura:", options=[opt[0] for opt in opts_c], key="edit_cultura_select")
            sel_tuple_c = [opt for opt in opts_c if opt[0] == sel_c_opt][0]
            row_idx_c, dados_c = sel_tuple_c[1], sel_tuple_c[2]

            with st.form("form_edit_cultura"):
                ec_codigo = st.text_input("Código", value=str(dados_c.get("Código", "")), disabled=True)
                ec_nome = st.text_input("Nome da Cultura", value=str(dados_c.get("Nome", "")))
                if st.form_submit_button("Atualizar Cultura"):
                    try:
                        nova_linha = [str(ec_codigo), str(ec_nome).strip()]
                        atualizar_linha_gspread("Cultura", 5, row_idx_c, nova_linha)
                        st.cache_data.clear()
                        st.success("✅ Cultura atualizada com sucesso!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao atualizar cultura: {ex}")

    # 3. EDIÇÃO DE TIPO DE APLICAÇÃO
    with ed_tab3:
        st.markdown("### Editar Tipo de Aplicação")
        if df_tp.empty:
            st.info("Nenhum tipo de aplicação cadastrado para editar.")
        else:
            opts_tp = [(f"{r.get('Nome', '')} (Cód: {r.get('Código', '')})", idx + 2, r) for idx, r in df_tp.iterrows()]
            sel_tp_opt = st.selectbox("Selecione o Tipo de Aplicação:", options=[opt[0] for opt in opts_tp], key="edit_tp_select")
            sel_tuple_tp = [opt for opt in opts_tp if opt[0] == sel_tp_opt][0]
            row_idx_tp, dados_tp = sel_tuple_tp[1], sel_tuple_tp[2]

            with st.form("form_edit_tp"):
                etp_codigo = st.text_input("Código", value=str(dados_tp.get("Código", "")), disabled=True)
                etp_nome = st.text_input("Nome do Tipo de Aplicação", value=str(dados_tp.get("Nome", "")))
                if st.form_submit_button("Atualizar Tipo de Aplicação"):
                    try:
                        nova_linha = [str(etp_codigo), str(etp_nome).strip()]
                        atualizar_linha_gspread("TpAplicação", 4, row_idx_tp, nova_linha)
                        st.cache_data.clear()
                        st.success("✅ Tipo de Aplicação atualizado com sucesso!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao atualizar tipo de aplicação: {ex}")

    # 4. EDIÇÃO DE PRODUTO
    with ed_tab4:
        st.markdown("### Editar Insumo / Produto")
        if df_produto.empty:
            st.info("Nenhum produto cadastrado para editar.")
        else:
            opts_p = [(f"{r.get('Nome', '')} (Cód: {r.get('Código', '')})", idx + 2, r) for idx, r in df_produto.iterrows()]
            sel_p_opt = st.selectbox("Selecione o Produto:", options=[opt[0] for opt in opts_p], key="edit_prod_select")
            sel_tuple_p = [opt for opt in opts_p if opt[0] == sel_p_opt][0]
            row_idx_p, dados_p = sel_tuple_p[1], sel_tuple_p[2]

            with st.form("form_edit_prod"):
                ep_codigo = st.text_input("Código", value=str(dados_p.get("Código", "")), disabled=True)
                ep_nome = st.text_input("Nome do Produto", value=str(dados_p.get("Nome", "")))
                if st.form_submit_button("Atualizar Produto"):
                    try:
                        nova_linha = [str(ep_codigo), str(ep_nome).strip()]
                        atualizar_linha_gspread("Produto", 2, row_idx_p, nova_linha)
                        st.cache_data.clear()
                        st.success("✅ Produto atualizado com sucesso!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao atualizar produto: {ex}")

    # 5. EDIÇÃO DE PRODUTOR
    with ed_tab5:
        st.markdown("### Editar Produtor")
        if df_produtor.empty:
            st.info("Nenum produtor cadastrado para editar.")
        else:
            opts_pr = [(f"{r.get('Nome', '')} (Cód: {r.get('Código', '')})", idx + 2, r) for idx, r in df_produtor.iterrows()]
            sel_pr_opt = st.selectbox("Selecione o Produtor:", options=[opt[0] for opt in opts_pr], key="edit_produtor_select")
            sel_tuple_pr = [opt for opt in opts_pr if opt[0] == sel_pr_opt][0]
            row_idx_pr, dados_pr = sel_tuple_pr[1], sel_tuple_pr[2]

            with st.form("form_edit_produtor"):
                epr_codigo = st.text_input("Código", value=str(dados_pr.get("Código", "")), disabled=True)
                epr_nome = st.text_input("Nome do Produtor", value=str(dados_pr.get("Nome", "")))
                if st.form_submit_button("Atualizar Produtor"):
                    try:
                        nova_linha = [str(epr_codigo), str(epr_nome).strip()]
                        atualizar_linha_gspread("Produtor", 3, row_idx_pr, nova_linha)
                        st.cache_data.clear()
                        st.success("✅ Produtor atualizado com sucesso!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao atualizar produtor: {ex}")
