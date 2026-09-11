import os
import subprocess
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as px_go
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="CVM Remuneração - Monitor de Administradores",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -----------------------------------------------------------------------------
# AUTENTICAÇÃO / TELA DE LOGIN
# -----------------------------------------------------------------------------
def check_password():
    """Retorna True se o usuário estiver autenticado com a senha correta."""
    # Obtém a senha configurada nos Secrets do Streamlit ou usa a senha padrão
    senha_correta = st.secrets.get("PASSWORD", "Xandao2019ryo!")

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if st.session_state["authenticated"]:
        return True

    # Tela de Login simplificada com suporte a ENTER
    _, col_login, _ = st.columns([1, 2, 1])
    with col_login:
        with st.form("login_form"):
            senha_input = st.text_input("Senha", type="password", key="password_input")
            btn_login = st.form_submit_button("Entrar", use_container_width=True)

            if btn_login:
                if senha_input.strip() == senha_correta.strip():
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("❌ Senha incorreta. Tente novamente.")

    return False

if not check_password():
    st.stop()

# -----------------------------------------------------------------------------
# Carregamento e Caching de Dados
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300)
def load_csv_data(file_basename):
    path = os.path.join(BASE_DIR, f"{file_basename}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
        return df
    except Exception as e:
        st.error(f"Erro ao carregar {file_basename}.csv: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_carteira():
    path = os.path.join(BASE_DIR, "carteira.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# -----------------------------------------------------------------------------
# Interface Principal e Filtros
# -----------------------------------------------------------------------------
st.title("📊 Monitor de Remuneração de Administradores (CVM)")
st.caption("Análise integrada de remuneração de companhias abertas brasileiras (FRE/CVM, DFP e Mercado)")

df_mercado = load_csv_data("monitor_mercado")
df_q82 = load_csv_data("monitor_total_orgao")
df_mmm = load_csv_data("monitor")
df_prev_real = load_csv_data("monitor_previsto_realizado")

if df_mercado.empty:
    st.warning("Nenhum dado encontrado em `monitor_mercado.csv`. Execute a coleta primeiro para gerar a base de dados.")

# --- BARRA LATERAL (FILTROS E LOGOUT) ---
st.sidebar.header("🔍 Filtros")

# Botão de Logout na Sidebar
if st.sidebar.button("🔒 Sair / Bloquear"):
    st.session_state["authenticated"] = False
    st.rerun()

st.sidebar.markdown("---")

# Filtro de Setor
setores_disp = ["Todos"]
if not df_mercado.empty and "setor" in df_mercado.columns:
    setores_unicos = sorted([s for s in df_mercado["setor"].dropna().unique() if str(s).strip()])
    setores_disp.extend(setores_unicos)

setor_sel = st.sidebar.selectbox("Setor", setores_disp, index=0)

# Filtro de Empresas
df_filtrado_setor = df_mercado.copy()
if setor_sel != "Todos" and not df_mercado.empty:
    df_filtrado_setor = df_mercado[df_mercado["setor"] == setor_sel]

empresas_disp = []
if not df_filtrado_setor.empty:
    col_nome = "apelido" if "apelido" in df_filtrado_setor.columns else "empresa"
    empresas_disp = sorted(df_filtrado_setor[col_nome].dropna().unique())

empresas_sel = st.sidebar.multiselect("Empresas", empresas_disp, default=[])

# Filtro de Anos
anos_min, anos_max = 2010, 2026
if not df_mercado.empty and "exercicio" in df_mercado.columns:
    anos_min = int(df_mercado["exercicio"].min())
    anos_max = int(df_mercado["exercicio"].max())

anos_sel = st.sidebar.slider("Intervalo de Anos", min_value=2007, max_value=2026, value=(max(2015, anos_min), anos_max))

# Filtragem dos DataFrames principais
def aplicar_filtros(df):
    if df.empty:
        return df
    df_sub = df.copy()
    if setor_sel != "Todos" and "setor" in df_sub.columns:
        df_sub = df_sub[df_sub["setor"] == setor_sel]
    if empresas_sel:
        col_nome = "apelido" if "apelido" in df_sub.columns else "empresa"
        if col_nome in df_sub.columns:
            df_sub = df_sub[df_sub[col_nome].isin(empresas_sel)]
    if "exercicio" in df_sub.columns:
        df_sub = df_sub[(df_sub["exercicio"] >= anos_sel[0]) & (df_sub["exercicio"] <= anos_sel[1])]
    return df_sub

df_mercado_f = aplicar_filtros(df_mercado)
df_q82_f = aplicar_filtros(df_q82)
df_mmm_f = aplicar_filtros(df_mmm)
df_prev_real_f = aplicar_filtros(df_prev_real)

# -----------------------------------------------------------------------------
# ABAS DA APLICAÇÃO
# -----------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📈 Visão Geral & Mercado",
    "💵 Composição das Verbas",
    "🏛️ Detalhe por Órgão",
    "🎯 Previsto vs Realizado",
    "🌐 Dashboard HTML Integrado",
    "⚙️ Atualizar Base de Dados"
])

# -----------------------------------------------------------------------------
# TAB 1: VISÃO GERAL & MERCADO
# -----------------------------------------------------------------------------
with tab1:
    if df_mercado_f.empty:
        st.info("Nenhum dado retornado para os filtros selecionados.")
    else:
        # KPIs principais
        col1, col2, col3, col4 = st.columns(4)
        rem_total = df_mercado_f["remuneracao_total"].sum()
        rem_med_emp = df_mercado_f.groupby("apelido")["remuneracao_total"].mean().mean() if "apelido" in df_mercado_f.columns else 0
        rem_rec_pct = df_mercado_f["rem_sobre_receita_pct"].dropna().median() if "rem_sobre_receita_pct" in df_mercado_f.columns else 0
        rem_mc_pct = df_mercado_f["rem_sobre_market_cap_pct"].dropna().median() if "rem_sobre_market_cap_pct" in df_mercado_f.columns else 0

        col1.metric("Remuneração Total (Filtro)", f"R$ {rem_total/1e6:,.1f}M".replace(",", "X").replace(".", ",").replace("X", "."))
        col2.metric("Remuneração Média Anual/Empresa", f"R$ {rem_med_emp/1e6:,.2f}M".replace(",", "X").replace(".", ",").replace("X", "."))
        col3.metric("Remuneração / Receita (Mediana)", f"{rem_rec_pct:.2f}%".replace(".", ","))
        col4.metric("Remuneração / Mkt Cap (Mediana)", f"{rem_mc_pct:.3f}%".replace(".", ","))

        st.markdown("---")

        st.subheader("Evolução Histórica da Remuneração Total (R$)")
        col_nome = "apelido" if "apelido" in df_mercado_f.columns else "empresa"
        
        fig_evol = px.line(
            df_mercado_f.sort_values("exercicio"),
            x="exercicio",
            y="remuneracao_total",
            color=col_nome,
            markers=True,
            labels={"exercicio": "Exercício", "remuneracao_total": "Remuneração Total (R$)", col_nome: "Empresa"},
            title="Remuneração Total por Empresa ao Longo dos Anos"
        )
        fig_evol.update_layout(hovermode="x unified", yaxis_tickprefix="R$ ")
        st.plotly_chart(fig_evol, use_container_width=True)

        st.subheader("Remuneração como % da Receita Líquida e do Valor de Mercado")
        c1, c2 = st.columns(2)
        with c1:
            if "rem_sobre_receita_pct" in df_mercado_f.columns:
                fig_rec = px.box(
                    df_mercado_f,
                    x=col_nome,
                    y="rem_sobre_receita_pct",
                    color=col_nome,
                    labels={"rem_sobre_receita_pct": "Remuneração / Receita (%)", col_nome: "Empresa"},
                    title="Distribuição (% da Receita Líquida)"
                )
                fig_rec.update_layout(showlegend=False)
                st.plotly_chart(fig_rec, use_container_width=True)
        with c2:
            if "rem_sobre_market_cap_pct" in df_mercado_f.columns:
                fig_mc = px.box(
                    df_mercado_f,
                    x=col_nome,
                    y="rem_sobre_market_cap_pct",
                    color=col_nome,
                    labels={"rem_sobre_market_cap_pct": "Remuneração / Market Cap (%)", col_nome: "Empresa"},
                    title="Distribuição (% do Market Cap)"
                )
                fig_mc.update_layout(showlegend=False)
                st.plotly_chart(fig_mc, use_container_width=True)

        st.subheader("Tabela de Dados Consolidada (Mercado & CVM)")
        st.dataframe(
            df_mercado_f[[c for c in ["apelido", "empresa", "setor", "exercicio", "remuneracao_total", "receita", "market_cap", "rem_sobre_receita_pct", "rem_sobre_market_cap_pct"] if c in df_mercado_f.columns]],
            use_container_width=True
        )

# -----------------------------------------------------------------------------
# TAB 2: COMPOSIÇÃO DAS VERBAS (QUADRO 8.2)
# -----------------------------------------------------------------------------
with tab2:
    st.subheader("Composição por Natureza da Verba (Quadro 8.2 CVM)")
    if df_q82_f.empty:
        st.info("Nenhum dado encontrado para o Quadro 8.2 com os filtros atuais.")
    else:
        verbas_cols = [
            "salario", "beneficios", "participacoes_comites", "outros_fixos",
            "bonus", "participacao_resultados", "participacao_reunioes", "comissoes",
            "outros_variaveis", "pos_emprego", "cessacao_cargo", "baseada_acoes"
        ]
        cols_existentes = [c for c in verbas_cols if c in df_q82_f.columns]
        
        # Agrupamento ano a ano das verbas
        df_verbas_ano = df_q82_f.groupby("exercicio")[cols_existentes].sum().reset_index()
        df_verbas_melt = df_verbas_ano.melt(id_vars=["exercicio"], var_name="Verba", value_name="Valor")

        fig_verbas = px.bar(
            df_verbas_melt,
            x="exercicio",
            y="Valor",
            color="Verba",
            title="Evolução Agregada das Verbas (Fixa vs Variável vs Ações)",
            labels={"exercicio": "Exercício", "Valor": "Valor (R$)"}
        )
        fig_verbas.update_layout(barmode="stack", hovermode="x unified")
        st.plotly_chart(fig_verbas, use_container_width=True)

        st.markdown("#### Detalhamento das Verbas por Órgão e Exercício")
        st.dataframe(df_q82_f, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 3: DETALHE POR ÓRGÃO
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("Remuneração por Órgão (Diretoria, Conselho Adm., Conselho Fiscal)")
    if df_q82_f.empty:
        st.info("Nenhum dado disponível para análise por órgão.")
    else:
        if "orgao" in df_q82_f.columns:
            col_nome = "apelido" if "apelido" in df_q82_f.columns else "empresa"
            df_orgao_sum = df_q82_f.groupby([col_nome, "orgao"])["total_orgao"].mean().reset_index()
            
            fig_orgao = px.bar(
                df_orgao_sum,
                x=col_nome,
                y="total_orgao",
                color="orgao",
                barmode="group",
                title="Remuneração Média Anual por Órgão da Companhia",
                labels={"total_orgao": "Total Médio Anual (R$)", col_nome: "Empresa", "orgao": "Órgão"}
            )
            st.plotly_chart(fig_orgao, use_container_width=True)

        if not df_mmm_f.empty:
            st.markdown("#### Faixas de Remuneração (Máxima, Média, Mínima - Item 8.16)")
            st.dataframe(df_mmm_f, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 4: PREVISTO VS REALIZADO
# -----------------------------------------------------------------------------
with tab4:
    st.subheader("Confronto: Remuneração Prevista vs. Realizada")
    if df_prev_real_f.empty:
        st.info("Nenhum dado de previsto x realizado encontrado.")
    else:
        st.caption("Comparação entre o orçamento previsto informado no FRE e a remuneração realizada no encerramento do exercício.")
        
        cols_pr = [c for c in ["apelido", "empresa", "orgao", "exercicio", "previsto_total", "realizado_total", "dif_total", "dif_total_pct"] if c in df_prev_real_f.columns]
        st.dataframe(df_prev_real_f[cols_pr], use_container_width=True)

        if "previsto_total" in df_prev_real_f.columns and "realizado_total" in df_prev_real_f.columns:
            fig_pr = px.scatter(
                df_prev_real_f,
                x="previsto_total",
                y="realizado_total",
                color="orgao" if "orgao" in df_prev_real_f.columns else None,
                hover_data=["apelido", "exercicio"] if "apelido" in df_prev_real_f.columns else [],
                title="Previsto vs Realizado (R$)"
            )
            # Linha de 100% (igualdade)
            max_val = max(df_prev_real_f["previsto_total"].max(), df_prev_real_f["realizado_total"].max())
            fig_pr.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val, line=dict(color="gray", dash="dash"))
            st.plotly_chart(fig_pr, use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 5: DASHBOARD HTML INTEGRADO
# -----------------------------------------------------------------------------
with tab5:
    st.subheader("Visualização do Dashboard HTML Standalone (`monitor.html`)")
    html_path = os.path.join(BASE_DIR, "monitor.html")
    if os.path.exists(html_path):
        st.caption("Exibindo a versão HTML offline original gerada por `cvm_dashboard.py`:")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=800, scrolling=True)
    else:
        st.warning("O arquivo `monitor.html` ainda não foi gerado. Execute a coleta com a opção de dashboard para gerá-lo.")

# -----------------------------------------------------------------------------
# TAB 6: ATUALIZAR BASE DE DADOS
# -----------------------------------------------------------------------------
with tab6:
    st.subheader("⚙️ Coleta e Atualização de Dados CVM")
    st.markdown("""
    Esta seção permite disparar a atualização dos dados diretamente dos servidores abertos da CVM e Yahoo Finance.
    Os dados coletados serão salvos em cache local (`.cvm_cache`) e nos arquivos `.csv` e `.html` do projeto.
    """)

    col_a, col_b = st.columns(2)
    with col_a:
        anos_coleta = st.text_input("Anos para Coleta (ex: 2010-2026)", value="2010-2026")
    with col_b:
        alvo_avulso = st.text_input("Ticker ou CNPJ avulso (opcional)", value="")

    if st.button("🚀 Iniciar Coleta CVM"):
        with st.spinner("Coletando dados da CVM e atualizando relatórios... Isso pode levar alguns instantes na primeira execução."):
            cmd = ["python", "cvm_remuneracao.py", "--carteira", "carteira.json", "--anos", anos_coleta, "--quadro82", "nao", "--dashboard", "monitor.html", "--out", "monitor.csv"]
            if alvo_avulso.strip():
                cmd.extend(["--alvos", alvo_avulso.strip()])
            
            res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
            if res.returncode == 0:
                st.success("Coleta e atualização concluídas com sucesso!")
                st.code(res.stdout)
                st.cache_data.clear()
            else:
                st.error("Ocorreu um erro durante a coleta de dados:")
                st.code(res.stderr)

st.markdown("---")
st.caption("CVM Remuneração Monitor • Antigravity AI")
