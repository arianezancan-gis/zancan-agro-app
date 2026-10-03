"""
Módulo de mapas do ZancanAgro
- Limite georreferenciado de cada talhão (Shapefile .zip, GeoJSON ou KML)
- Ortomosaicos por talhão (vários voos por área), exibidos como camadas de blocos
Os dados ficam em duas abas novas da planilha "ZancanAgro": "Geometria" e "Ortomosaico"
(criadas automaticamente na primeira vez).
"""
import json
import os
import tempfile
import zipfile
from datetime import date
from urllib.parse import quote

import folium
import geopandas as gpd
import gspread
import pandas as pd
import requests
import streamlit as st
from shapely.geometry import mapping, shape
from streamlit_folium import st_folium

ABA_GEOMETRIA = "Geometria"
COLS_GEOMETRIA = ["Código Talhão", "Produtor", "Nome da Área",
                  "Área Calculada (ha)", "Atualizado em", "GeoJSON"]

ABA_ORTO = "Ortomosaico"
COLS_ORTO = ["Código", "Código Talhão", "Produtor", "Nome da Área",
             "Data do Voo", "Descrição", "Tipo", "URL", "Zoom Máximo"]

TIPO_XYZ = "Tile Layer ArcGIS / URL de blocos (XYZ)"
TIPO_COG = "COG (GeoTIFF otimizado na nuvem)"

TITILER = "https://titiler.xyz"   # servidor público de demonstração do TiTiler
LIMITE_CELULA = 45000             # Google Sheets aceita até 50.000 caracteres por célula


# ---------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------
def obter_aba(abrir_planilha, nome, cabecalho):
    """Abre a aba; se não existir, cria com o cabeçalho."""
    planilha = abrir_planilha()
    try:
        return planilha.worksheet(nome)
    except gspread.WorksheetNotFound:
        ws = planilha.add_worksheet(title=nome, rows=500, cols=len(cabecalho))
        ws.append_row(cabecalho, value_input_option="RAW")
        return ws


def _ler_aba(abrir_planilha, nome, cabecalho):
    linhas = obter_aba(abrir_planilha, nome, cabecalho).get_all_values()
    if len(linhas) <= 1:
        return pd.DataFrame(columns=cabecalho)
    cab = [str(h).strip() for h in linhas[0]]
    df = pd.DataFrame(linhas[1:], columns=cab)
    for c in cabecalho:          # garante colunas novas mesmo em planilhas antigas
        if c not in df.columns:
            df[c] = ""
    df["_linha"] = range(2, len(df) + 2)   # nº da linha na planilha
    return df[df.iloc[:, 0].astype(str).str.strip() != ""]


@st.cache_data(ttl=30)
def carregar_dados_mapa(_abrir_planilha):
    try:
        df_geo = _ler_aba(_abrir_planilha, ABA_GEOMETRIA, COLS_GEOMETRIA)
        df_orto = _ler_aba(_abrir_planilha, ABA_ORTO, COLS_ORTO)
        return df_geo, df_orto
    except Exception as e:
        st.error(f"Erro ao carregar dados de mapa: {e}")
        return pd.DataFrame(columns=COLS_GEOMETRIA), pd.DataFrame(columns=COLS_ORTO)


# ---------------------------------------------------------
# Arquivos geográficos
# ---------------------------------------------------------
def ler_arquivo_geo(arquivo):
    """Lê .zip (shapefile), .geojson/.json ou .kml e devolve GeoDataFrame em WGS84."""
    nome = arquivo.name.lower()
    with tempfile.TemporaryDirectory() as tmp:
        if nome.endswith(".zip"):
            with zipfile.ZipFile(arquivo) as z:
                z.extractall(tmp)
            shps = [os.path.join(r, f) for r, _, fs in os.walk(tmp) for f in fs
                    if f.lower().endswith(".shp") and "__MACOSX" not in r
                    and not f.startswith("._")]
            if not shps:
                raise ValueError("Nenhum arquivo .shp encontrado dentro do .zip.")
            caminho = shps[0]
        else:
            caminho = os.path.join(tmp, os.path.basename(arquivo.name))
            with open(caminho, "wb") as f:
                f.write(arquivo.getbuffer())
        gdf = gpd.read_file(caminho)

    if gdf.empty:
        raise ValueError("O arquivo não tem feições.")
    if gdf.crs is None:
        if nome.endswith(".zip"):
            raise ValueError("Shapefile sem o arquivo .prj — não dá para saber a projeção. "
                             "Inclua o .prj no .zip.")
        gdf = gdf.set_crs(4326)   # GeoJSON/KML são WGS84 por padrão

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
    if gdf.empty:
        raise ValueError("O arquivo não contém polígonos (pontos e linhas são ignorados).")
    return gdf.to_crs(4326)


def area_hectares(gdf):
    return float(gdf.to_crs(gdf.estimate_utm_crs()).area.sum() / 10_000)


def _arredondar(coords, casas=7):
    if isinstance(coords, (list, tuple)):
        if coords and isinstance(coords[0], (int, float)):
            return [round(c, casas) for c in coords]
        return [_arredondar(c, casas) for c in coords]
    return coords


def geometria_para_texto(geom):
    """Converte para GeoJSON compacto; simplifica só se passar do limite da célula."""
    for tol in [0, 1e-7, 5e-7, 1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5, 1e-4]:
        g = geom.simplify(tol, preserve_topology=True) if tol else geom
        gj = mapping(g)
        gj = {"type": gj["type"], "coordinates": _arredondar(gj["coordinates"])}
        txt = json.dumps(gj, separators=(",", ":"))
        if len(txt) <= LIMITE_CELULA:
            return txt, tol
    raise ValueError("Polígono complexo demais para caber numa célula do Google Sheets.")


# ---------------------------------------------------------
# URLs de blocos
# ---------------------------------------------------------
def montar_url_tiles(tipo, url):
    url = str(url).strip()
    if tipo == TIPO_COG:
        return (f"{TITILER}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}@1x"
                f"?url={quote(url, safe='')}")
    if "{z}" in url:
        return url
    base, _, query = url.partition("?")
    base = base.rstrip("/")
    if base.endswith(("MapServer", "ImageServer")):
        return f"{base}/tile/{{z}}/{{y}}/{{x}}" + (f"?{query}" if query else "")
    return url


def limites_cog(url):
    """Pergunta ao TiTiler a extensão do COG (usado quando o talhão não tem limite)."""
    try:
        r = requests.get(f"{TITILER}/cog/bounds", params={"url": url}, timeout=8)
        r.raise_for_status()
        return tuple(r.json()["bounds"])
    except Exception:
        return None


# ---------------------------------------------------------
# Mapa
# ---------------------------------------------------------
def _resumo_aplicacoes(df_app, produtor, talhao):
    """Tabela HTML com as últimas aplicações do talhão (colunas na ordem gravada pelo app)."""
    if df_app is None or df_app.empty or df_app.shape[1] < 7:
        return ""
    a = df_app[(df_app.iloc[:, 0].str.upper() == str(produtor).upper()) &
               (df_app.iloc[:, 1].str.upper() == str(talhao).upper())].copy()
    if a.empty:
        return "<i>Sem aplicações registradas</i>"
    a["_d"] = pd.to_datetime(a.iloc[:, 6], format="%d/%m/%Y", errors="coerce")
    a = a.sort_values("_d", ascending=False).head(5)
    linhas = "".join(
        f"<tr><td>{r.iloc[6]}</td><td>{r.iloc[2]}</td><td>{r.iloc[3]}</td><td>{r.iloc[4]}</td></tr>"
        for _, r in a.iterrows())
    return ("<b>Últimas aplicações</b><table style='font-size:11px'>"
            "<tr><th>Data</th><th>Tipo</th><th>Produto</th><th>Dose/ha</th></tr>"
            f"{linhas}</table>")


def desenhar_mapa(df_geo_sel, df_orto_sel, df_app=None, altura=600, chave="mapa"):
    m = folium.Map(location=[-15.8, -47.9], zoom_start=4, tiles=None,
                   max_zoom=22, control_scale=True)
    folium.TileLayer("Esri.WorldImagery", name="Satélite (Esri)",
                     max_zoom=22, max_native_zoom=19).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap",
                     max_zoom=22, max_native_zoom=19).add_to(m)

    extensoes = []

    # Ortomosaicos: só o voo mais recente de cada talhão começa ligado
    if df_orto_sel is not None and not df_orto_sel.empty:
        o = df_orto_sel.copy()
        o["_d"] = pd.to_datetime(o["Data do Voo"], format="%d/%m/%Y", errors="coerce")
        o = o.sort_values("_d")
        ultimos = set(o.groupby("Código Talhão").tail(1).index)
        for idx, r in o.iterrows():
            try:
                zmax = int(float(str(r.get("Zoom Máximo") or 21).replace(",", ".")))
            except ValueError:
                zmax = 21
            nome = f"🛩️ {r['Nome da Área']} – {r['Data do Voo']}"
            if str(r.get("Descrição", "")).strip():
                nome += f" ({r['Descrição']})"
            folium.TileLayer(
                tiles=montar_url_tiles(r["Tipo"], r["URL"]),
                attr="Ortomosaico ZancanAgro", name=nome,
                overlay=True, control=True, show=idx in ultimos,
                max_zoom=22, max_native_zoom=zmax,
            ).add_to(m)
            if r["Tipo"] == TIPO_COG and (df_geo_sel is None or df_geo_sel.empty):
                b = limites_cog(r["URL"])
                if b:
                    extensoes.append(b)

    # Limites dos talhões
    if df_geo_sel is not None and not df_geo_sel.empty:
        grupo = folium.FeatureGroup(name="Limites dos talhões", show=True)
        for _, g in df_geo_sel.iterrows():
            try:
                geom = json.loads(g["GeoJSON"])
            except (ValueError, TypeError):
                continue
            titulo = f"{g['Nome da Área']} — {g['Produtor']}"
            popup = (f"<b>{titulo}</b><br>Área calculada: {g['Área Calculada (ha)']} ha<br><br>"
                     + _resumo_aplicacoes(df_app, g["Produtor"], g["Nome da Área"]))
            folium.GeoJson(
                geom,
                style_function=lambda _: {"color": "#FFD400", "weight": 3, "fillOpacity": 0.05},
                highlight_function=lambda _: {"weight": 5, "fillOpacity": 0.15},
                tooltip=titulo,
                popup=folium.Popup(popup, max_width=380),
            ).add_to(grupo)
            extensoes.append(shape(geom).bounds)
        grupo.add_to(m)

    if extensoes:
        minx = min(b[0] for b in extensoes); miny = min(b[1] for b in extensoes)
        maxx = max(b[2] for b in extensoes); maxy = max(b[3] for b in extensoes)
        m.fit_bounds([[miny, minx], [maxy, maxx]])

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, height=altura, use_container_width=True, returned_objects=[], key=chave)


# ---------------------------------------------------------
# Interface
# ---------------------------------------------------------
def _opcoes_talhoes(df_talhao, produtor="Todos"):
    if df_talhao.empty or "Nome da Área" not in df_talhao.columns:
        return {}
    df = df_talhao
    if produtor != "Todos":
        df = df[df["Produtor"].str.upper() == str(produtor).upper()]
    return {f"{r.get('Produtor', '')} - {r.get('Nome da Área', '')} (Cód: {r.get('Código', '')})": r
            for _, r in df.iterrows() if str(r.get("Nome da Área", "")).strip()}


def render_aba_mapas(abrir_planilha, df_talhao, df_app, lista_produtores, parse_float):
    df_geo, df_orto = carregar_dados_mapa(abrir_planilha)

    sub_ver, sub_lim, sub_orto = st.tabs([
        "🗺️ Visualizar", "📐 Limite do Talhão (Shapefile)", "🛩️ Ortomosaicos"])

    # ---------- VISUALIZAR ----------
    with sub_ver:
        c1, c2 = st.columns([1, 2])
        with c1:
            prod = st.selectbox("Produtor", ["Todos"] + lista_produtores, key="mapa_produtor")
        opcoes = _opcoes_talhoes(df_talhao, prod)
        with c2:
            sel = st.multiselect("Talhões", list(opcoes.keys()),
                                 default=list(opcoes.keys()), key="mapa_talhoes")
        mostrar_orto = st.toggle("Mostrar ortomosaicos", value=True)

        codigos = [str(opcoes[k].get("Código", "")) for k in sel]
        g_sel = df_geo[df_geo["Código Talhão"].astype(str).isin(codigos)]
        o_sel = df_orto[df_orto["Código Talhão"].astype(str).isin(codigos)] if mostrar_orto else None

        if not sel:
            st.info("Selecione ao menos um talhão.")
        else:
            desenhar_mapa(g_sel, o_sel, df_app, chave="mapa_principal")

            status = pd.DataFrame([{
                "Talhão": opcoes[k].get("Nome da Área", ""),
                "Produtor": opcoes[k].get("Produtor", ""),
                "Limite": "✅" if c in set(df_geo["Código Talhão"].astype(str)) else "—",
                "Ortomosaicos": int((df_orto["Código Talhão"].astype(str) == c).sum()),
            } for k, c in zip(sel, codigos)])
            st.dataframe(status, hide_index=True, use_container_width=True)

    # ---------- LIMITE (SHAPEFILE) ----------
    with sub_lim:
        st.markdown("### Importar limite georreferenciado do talhão")
        st.caption("Envie um **.zip** com o shapefile (.shp, .shx, .dbf **e .prj**), "
                   "ou um **.geojson** / **.kml**. Se houver vários polígonos, eles são unidos num só.")
        todas = _opcoes_talhoes(df_talhao)
        if not todas:
            st.info("Cadastre um talhão primeiro.")
        else:
            alvo = st.selectbox("Talhão", list(todas.keys()), key="lim_talhao")
            r_t = todas[alvo]
            cod = str(r_t.get("Código", ""))
            if cod in set(df_geo["Código Talhão"].astype(str)):
                st.warning("Este talhão já tem limite cadastrado — o novo arquivo vai substituí-lo.")

            arq = st.file_uploader("Arquivo do limite", type=["zip", "geojson", "json", "kml"],
                                   key="lim_arquivo")
            if arq is not None:
                try:
                    gdf = ler_arquivo_geo(arq)
                    geom = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") \
                        else gdf.geometry.unary_union
                    area = area_hectares(gpd.GeoDataFrame(geometry=[geom], crs=4326))
                    texto, tol = geometria_para_texto(geom)

                    area_real = parse_float(r_t.get("Área Real", 0))
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Polígonos no arquivo", len(gdf))
                    m2.metric("Área calculada", f"{area:,.2f} ha")
                    m3.metric("Área Real cadastrada", f"{area_real:,.2f} ha",
                              delta=f"{area - area_real:+,.2f} ha" if area_real else None)
                    if tol:
                        st.info("O polígono tinha muitos vértices e foi simplificado levemente "
                                "para caber na planilha (diferença menor que ~10 m).")

                    prev = pd.DataFrame([{
                        "Código Talhão": cod, "Produtor": r_t.get("Produtor", ""),
                        "Nome da Área": r_t.get("Nome da Área", ""),
                        "Área Calculada (ha)": f"{area:.2f}", "GeoJSON": texto}])
                    desenhar_mapa(prev, None, altura=400, chave="mapa_previa")

                    atualizar_area = st.checkbox("Atualizar também a 'Área Real' do talhão com a área calculada")

                    if st.button("💾 Salvar limite no Google Drive", type="primary"):
                        ws = obter_aba(abrir_planilha, ABA_GEOMETRIA, COLS_GEOMETRIA)
                        linha = [cod, r_t.get("Produtor", ""), r_t.get("Nome da Área", ""),
                                 round(area, 2), date.today().strftime("%d/%m/%Y"), texto]
                        existente = df_geo[df_geo["Código Talhão"].astype(str) == cod]
                        if existente.empty:
                            ws.append_row(linha, value_input_option="RAW")
                        else:
                            n = int(existente["_linha"].iloc[0])
                            ws.update(range_name=f"A{n}:F{n}", values=[linha],
                                      value_input_option="RAW")

                        if atualizar_area and "Área Real" in df_talhao.columns:
                            n_t = int(df_talhao.index[df_talhao["Código"].astype(str) == cod][0]) + 2
                            col = list(df_talhao.columns).index("Área Real") + 1
                            planilha = abrir_planilha()
                            try:
                                ws_t = planilha.worksheet("Talhao")
                            except gspread.WorksheetNotFound:
                                ws_t = planilha.get_worksheet(1)
                            ws_t.update_cell(n_t, col, f"{area:.2f}".replace(".", ","))

                        st.cache_data.clear()
                        st.success("✅ Limite salvo!")
                        st.rerun()
                except Exception as ex:
                    st.error(f"Não foi possível ler o arquivo: {ex}")

    # ---------- ORTOMOSAICOS ----------
    with sub_orto:
        st.markdown("### Cadastrar ortomosaico")
        with st.expander("ℹ️ Como obter a URL do ortomosaico"):
            st.markdown(
                "O ortomosaico **não é enviado para o app** (os arquivos são grandes demais). "
                "Ele fica hospedado na nuvem e o app guarda só o link.\n\n"
                "**Opção 1 – ArcGIS Online (Tile Layer)**\n"
                "1. No ArcGIS Pro, rode *Create Map Tile Package* no ortomosaico (até o nível 21 ou 22) "
                "e envie o `.tpkx` ao ArcGIS Online publicando como *Tile Layer*.\n"
                "2. Compartilhe a camada como **Pública**.\n"
                "3. Copie a URL do serviço, ex.: `https://tiles.arcgis.com/tiles/<org>/arcgis/rest/services/Fazenda_Gleba01_2026_09/MapServer`\n\n"
                "**Opção 2 – COG em um bucket**\n"
                "1. Converta: `gdal_translate orto.tif orto_cog.tif -of COG -co COMPRESS=JPEG -co QUALITY=85`\n"
                "2. Envie para um bucket público (Cloudflare R2, Supabase Storage, Google Cloud Storage, S3).\n"
                "3. Cole o link direto do arquivo `.tif`. *Google Drive não funciona para isso.*")

        todas = _opcoes_talhoes(df_talhao)
        if not todas:
            st.info("Cadastre um talhão primeiro.")
        else:
            with st.form("form_orto", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    o_talhao = st.selectbox("Talhão", list(todas.keys()))
                    o_data = st.date_input("Data do voo", value=date.today(), format="DD/MM/YYYY")
                    o_desc = st.text_input("Descrição (opcional)", placeholder="ex: pós-emergência, RGB")
                with c2:
                    o_tipo = st.radio("Tipo de link", [TIPO_XYZ, TIPO_COG])
                    o_url = st.text_input("URL")
                    o_zoom = st.number_input("Zoom máximo do ortomosaico", 15, 23, 21,
                                             help="Último nível de blocos gerado. Se o mapa ficar "
                                                  "em branco ao aproximar, diminua este valor.")
                if st.form_submit_button("💾 Salvar ortomosaico", type="primary"):
                    url_tiles = montar_url_tiles(o_tipo, o_url)
                    if not o_url.strip().lower().startswith("http"):
                        st.error("Informe uma URL começando com http(s).")
                    elif "{z}" not in url_tiles:
                        st.error("Não reconheci a URL. Use um serviço .../MapServer, .../ImageServer "
                                 "ou um modelo com {z}/{x}/{y}.")
                    else:
                        r_t = todas[o_talhao]
                        ws = obter_aba(abrir_planilha, ABA_ORTO, COLS_ORTO)
                        codigos = pd.to_numeric(df_orto["Código"], errors="coerce")
                        prox = int(codigos.max()) + 1 if codigos.notna().any() else 1
                        ws.append_row([prox, str(r_t.get("Código", "")), r_t.get("Produtor", ""),
                                       r_t.get("Nome da Área", ""), o_data.strftime("%d/%m/%Y"),
                                       o_desc.strip(), o_tipo, o_url.strip(), int(o_zoom)],
                                      value_input_option="RAW")
                        st.cache_data.clear()
                        st.success("✅ Ortomosaico cadastrado!")
                        st.rerun()

        st.markdown("### Ortomosaicos cadastrados")
        if df_orto.empty:
            st.info("Nenhum ortomosaico cadastrado.")
        else:
            st.dataframe(df_orto.drop(columns=["_linha"]), hide_index=True, use_container_width=True)
            rot = {f"{r['Produtor']} - {r['Nome da Área']} – {r['Data do Voo']} (Cód: {r['Código']})": r
                   for _, r in df_orto.iterrows()}
            c1, c2 = st.columns([3, 1])
            with c1:
                rem = st.selectbox("Remover ortomosaico", list(rot.keys()), key="orto_remover")
            with c2:
                st.write("")
                st.write("")
                if st.button("🗑️ Remover"):
                    ws = obter_aba(abrir_planilha, ABA_ORTO, COLS_ORTO)
                    ws.delete_rows(int(rot[rem]["_linha"]))
                    st.cache_data.clear()
                    st.rerun()
