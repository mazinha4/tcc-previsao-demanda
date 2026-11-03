"""
Ferramenta de apoio à decisão para planejamento da produção de restaurantes
a partir dos relatórios do iFood (Portal do Parceiro).

Este arquivo cuida apenas da interface. Toda a lógica de cálculo está em
motor.py.

Execução local:
    pip install -r requirements.txt
    streamlit run app.py
"""

import math

import streamlit as st

from motor import (
    DIAS_SEMANA,
    calcular_previsao,
    calcular_proxima_semana,
    calcular_sazonalidade,
    classificar_itens,
    comparar_janelas,
    converter_para_producao,
    encontrar_sobreposicoes,
    incorporar,
    ler_relatorio_cardapio,
    ler_relatorio_vendas,
    mapear_dias_para_datas,
    ordenar_periodos,
    validar_historico,
    validar_modelo,
)
from persistencia import (
    carregar_historico,
    criar_conta,
    entrar,
    modo_atual,
    salvar_historico,
)

st.set_page_config(
    page_title="Planejamento de Produção | iFood",
    page_icon="\U0001F4CA",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #FFF9F2 0%, #FFFDFB 320px);
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #FBE4CC;
        border-radius: 14px;
        padding: 14px 16px 10px 16px;
        box-shadow: 0 2px 6px rgba(230, 145, 56, 0.08);
    }
    div[data-testid="stMetricLabel"] { color: #A8642B; }
    button[data-baseweb="tab"] {
        border-radius: 10px 10px 0 0 !important;
    }
    div[data-testid="stDataFrame"] {
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid #F1E2D0;
    }
    div[data-testid="stExpander"], div[data-testid="stForm"] {
        border-radius: 14px !important;
        border: 1px solid #F1E2D0 !important;
    }
    h1, h2, h3 { color: #7A4A1D; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Login / cadastro do restaurante
# --------------------------------------------------------------------------

if "restaurante_id" not in st.session_state:
    st.title("📊 Planejamento de produção a partir das vendas do iFood")
    st.caption(
        "Cada restaurante tem sua própria conta e seu próprio histórico. "
        "Crie uma conta na primeira vez; nas próximas, é só entrar."
    )

    aba_entrar, aba_criar = st.tabs(["Entrar", "Criar conta"])

    with aba_entrar:
        with st.form("form_entrar"):
            nome = st.text_input("Nome do restaurante", key="nome_entrar")
            senha = st.text_input("Senha", type="password", key="senha_entrar")
            enviado = st.form_submit_button("Entrar", type="primary", use_container_width=True)
        if enviado:
            ok, mensagem, restaurante_id, nome_salvo = entrar(nome, senha)
            if ok:
                st.session_state.restaurante_id = restaurante_id
                st.session_state.nome_restaurante = nome_salvo
                st.rerun()
            else:
                st.error(mensagem)

    with aba_criar:
        with st.form("form_criar"):
            nome_novo = st.text_input("Nome do restaurante", key="nome_criar")
            senha_novo = st.text_input("Escolha uma senha", type="password", key="senha_criar")
            confirmar = st.text_input("Confirme a senha", type="password", key="senha_criar_2")
            criar = st.form_submit_button("Criar conta", type="primary", use_container_width=True)
        if criar:
            if senha_novo != confirmar:
                st.error("As senhas digitadas não são iguais.")
            else:
                ok, mensagem, restaurante_id = criar_conta(nome_novo, senha_novo)
                if ok:
                    st.session_state.restaurante_id = restaurante_id
                    st.session_state.nome_restaurante = nome_novo.strip()
                    st.success(mensagem)
                    st.rerun()
                else:
                    st.error(mensagem)

    st.stop()

# --------------------------------------------------------------------------
# A partir daqui, o restaurante já está autenticado
# --------------------------------------------------------------------------

st.title("📊 Planejamento de produção a partir das vendas do iFood")
st.caption(f"Restaurante: **{st.session_state.nome_restaurante}**")

if "itens" not in st.session_state:
    st.session_state.itens, st.session_state.dias = carregar_historico(
        st.session_state.restaurante_id
    )

with st.sidebar:
    st.header("1. Enviar relatórios")
    arq_cardapio = st.file_uploader(
        "Relatório de cardápio (.xlsx)", type=["xlsx", "xls"],
        help="Portal do iFood › Relatórios › Operação › Cardápio. Usa a aba 'Itens'.",
    )
    arq_vendas = st.file_uploader(
        "Relatório de vendas (.xlsx)", type=["xlsx", "xls"],
        help="Portal do iFood › Relatórios › Operação › Vendas. Usa a aba 'Dias com mais vendas'.",
    )

    if st.button("Processar e salvar no histórico", type="primary",
                 use_container_width=True, disabled=not (arq_cardapio and arq_vendas)):
        try:
            novos_itens = ler_relatorio_cardapio(arq_cardapio)
            novos_dias = ler_relatorio_vendas(arq_vendas)

            if set(novos_itens["periodo"]) != set(novos_dias["periodo"]):
                st.warning(
                    "Os dois relatórios são de períodos diferentes: "
                    f"{sorted(set(novos_itens['periodo']))} e "
                    f"{sorted(set(novos_dias['periodo']))}. "
                    "Confira antes de confiar na previsão."
                )

            sobreposicoes = encontrar_sobreposicoes(st.session_state.itens, novos_itens)
            if sobreposicoes:
                linhas = "\n".join(
                    f"- **{existente}** colide com **{novo}** entre "
                    f"{ini_conf:%d/%m/%Y} e {fim_conf:%d/%m/%Y}"
                    for existente, novo, ini_conf, fim_conf in sobreposicoes
                )
                st.error(
                    "Não salvei — esse envio tem dias que já estão no histórico "
                    "com outro período:\n\n" + linhas + "\n\n"
                    "O relatório do iFood só traz a quantidade total do período, "
                    "não por dia, então não dá para separar automaticamente o que "
                    "é repetido. Baixe do Portal do Parceiro um relatório apenas do "
                    "intervalo que ainda falta (sem repetir os dias acima) e "
                    "envie de novo."
                )
            else:
                st.session_state.itens = incorporar(st.session_state.itens, novos_itens)
                st.session_state.dias = incorporar(st.session_state.dias, novos_dias)
                salvar_historico(
                    st.session_state.restaurante_id,
                    st.session_state.itens, st.session_state.dias,
                )
                st.success(f"Período {novos_itens['periodo'].iloc[0]} registrado.")
        except Exception as erro:
            st.error(f"Não consegui ler o arquivo: {erro}")

    st.divider()
    st.header("2. Parâmetros")
    margem = st.slider(
        "Margem de segurança (%)", 0, 50, 10,
        help="Produção extra sobre a previsão para reduzir risco de ruptura.",
    ) / 100

    arredondar = st.checkbox("Arredondar para cima (unidades inteiras)", value=True)

    converter = st.checkbox(
        "Planejar por salgado (converter combos, retirar bebidas)", value=True,
        help=(
            "Combos com um salgado identificado (ex.: 'Coxinha Cremosa + Suco') "
            "são somados a esse salgado. Bebidas e combos que não dizem qual "
            "salgado vem dentro ficam fora do plano."
        ),
    )

    st.divider()
    st.header("3. Histórico")
    st.caption(f"Armazenamento: {modo_atual()}")
    if not st.session_state.itens.empty:
        disponiveis = ordenar_periodos(st.session_state.itens)

        # Média móvel: só os N períodos mais recentes entram no cálculo.
        if len(disponiveis) > 1:
            n_recentes = st.slider(
                "Usar os últimos N períodos", 1, len(disponiveis),
                len(disponiveis),
                help=(
                    "Média móvel: só os períodos mais recentes entram na "
                    "previsão, para ela acompanhar mudanças nas vendas. "
                    "Enviando um relatório por semana, cada período é uma "
                    "semana. A aba Validação mostra qual N erra menos."
                ),
            )
        else:
            n_recentes = 1

        selecionados = st.multiselect(
            "Períodos usados no cálculo", disponiveis,
            default=disponiveis[-n_recentes:],
        )
        if st.button("Limpar todo o histórico", use_container_width=True):
            vazio_itens = st.session_state.itens.iloc[0:0]
            vazio_dias = st.session_state.dias.iloc[0:0]
            salvar_historico(st.session_state.restaurante_id, vazio_itens, vazio_dias)
            st.session_state.itens, st.session_state.dias = carregar_historico(
                st.session_state.restaurante_id
            )
            st.rerun()
    else:
        selecionados = []
        n_recentes = None

    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        for chave in ("restaurante_id", "nome_restaurante", "itens", "dias"):
            st.session_state.pop(chave, None)
        st.rerun()

# --------------------------------------------------------------------------

if st.session_state.itens.empty:
    st.info(
        "Nenhum dado carregado ainda. Envie os dois relatórios na barra lateral "
        "para começar."
    )
    st.stop()

# Os dados originais ficam guardados como vieram do iFood; a conversão para
# itens de produção é feita aqui, na hora do cálculo.
base_itens = (
    converter_para_producao(st.session_state.itens) if converter
    else st.session_state.itens
)

itens = base_itens[base_itens["periodo"].isin(selecionados)]
dias = st.session_state.dias[st.session_state.dias["periodo"].isin(selecionados)]

if itens.empty or dias.empty:
    st.warning("Selecione ao menos um período na barra lateral.")
    st.stop()

sazonalidade, dias_operados, total_pedidos = calcular_sazonalidade(dias)
if sazonalidade.empty:
    st.error("Não há pedidos suficientes nos períodos selecionados.")
    st.stop()

colunas_dia = [str(d) for d in sazonalidade["Dia"]]

inicio_semana, fim_semana = calcular_proxima_semana(itens)
mapa_datas = mapear_dias_para_datas(inicio_semana) if inicio_semana else {}
rotulos_dia = {
    d: f"{d} ({mapa_datas[d]:%d/%m})" if d in mapa_datas else d
    for d in colunas_dia
}

if inicio_semana:
    st.header(
        f"📦 Planejamento da produção — semana de "
        f"{inicio_semana:%d/%m} a {fim_semana:%d/%m/%Y}"
    )
    st.caption(
        f"Calculado a partir do último dado enviado ({itens['fim'].max():%d/%m/%Y}), "
        f"usando {len(selecionados)} período(s) do histórico. "
        "Envie os relatórios da semana seguinte assim que ela terminar para "
        "manter essa data sempre atualizada."
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric("Dias de operação analisados", dias_operados)
c2.metric("Pedidos no período", f"{int(total_pedidos):,}".replace(",", "."))
c3.metric("Itens de produção" if converter else "Itens no cardápio", itens["item"].nunique())
melhor = sazonalidade.loc[sazonalidade["Índice de sazonalidade"].idxmax()]
c4.metric(
    "Dia mais forte", str(melhor["Dia"]),
    f"{(melhor['Índice de sazonalidade'] - 1) * 100:+.0f}% vs. média",
)

aba1, aba2, aba3, aba4 = st.tabs([
    "🍽️ Produção da semana", "📅 Sazonalidade", "📈 Ranking de itens", "✅ Validação",
])

with aba1:
    previsao = calcular_previsao(itens, sazonalidade, dias_operados, margem)

    st.markdown(f"#### 🍽️ Quanto produzir de cada item")
    legendas = "🔥 top vendas · ⭐ vende bem"
    st.caption(legendas + (f" · valores já incluem margem de {margem:.0%}" if margem else ""))

    quantos = st.number_input(
        "Mostrar os N itens mais vendidos", 5, max(5, len(previsao)),
        min(20, len(previsao)), step=5,
    )
    tabela = previsao.head(int(quantos)).copy()

    total_geral = previsao["Total da semana"].sum()
    tabela["_acumulado"] = tabela["Total da semana"].cumsum() / total_geral if total_geral else 0
    def _selo(linha):
        if linha["_acumulado"] <= 0.5:
            return "🔥"
        if linha["_acumulado"] <= 0.8:
            return "⭐"
        return "·"
    tabela.insert(0, " ", tabela.apply(_selo, axis=1))

    exibir = tabela[[" ", "Item"] + colunas_dia + ["Total da semana"]].copy()
    if arredondar:
        # Arredonda cada dia para cima e soma os dias arredondados, para o
        # total da semana bater com o que a cozinha vai produzir.
        for coluna in colunas_dia:
            exibir[coluna] = exibir[coluna].map(lambda v: int(math.ceil(v)))
        exibir["Total da semana"] = exibir[colunas_dia].sum(axis=1)
    else:
        for coluna in colunas_dia + ["Total da semana"]:
            exibir[coluna] = exibir[coluna].round(1)

    colunas_dia_rotuladas = [rotulos_dia[d] for d in colunas_dia]
    exibir = exibir.rename(columns=rotulos_dia)

    st.dataframe(
        exibir.style.background_gradient(cmap="Oranges", subset=colunas_dia_rotuladas),
        use_container_width=True, hide_index=True,
    )

    st.download_button(
        "⬇️ Baixar plano de produção (CSV)",
        exibir.to_csv(index=False).encode("utf-8-sig"),
        file_name="plano_producao_semanal.csv",
        mime="text/csv",
    )

    dia_escolhido = st.selectbox(
        "Ver lista de produção de um dia específico",
        colunas_dia, format_func=lambda d: rotulos_dia.get(d, d),
    )
    lista = tabela[["Item", dia_escolhido]].copy()
    lista = lista[lista[dia_escolhido] > 0].rename(columns={dia_escolhido: "Produzir"})
    if arredondar:
        lista["Produzir"] = lista["Produzir"].map(lambda v: int(math.ceil(v)))
    else:
        lista["Produzir"] = lista["Produzir"].round(1)
    st.dataframe(lista, use_container_width=True, hide_index=True)

    if converter:
        with st.expander("Como os itens do cardápio viraram itens de produção"):
            originais = st.session_state.itens[
                st.session_state.itens["periodo"].isin(selecionados)
            ]
            classificacao = classificar_itens(originais)
            resumo = (
                classificacao.groupby("Tratamento")["Quantidade"]
                .agg(Itens="count", Unidades="sum").reset_index()
            )
            st.dataframe(resumo, use_container_width=True, hide_index=True)
            fora = classificacao[classificacao["Item de produção"].isna()]["Quantidade"].sum()
            total = classificacao["Quantidade"].sum()
            if total:
                st.caption(
                    f"{int(fora)} de {int(total)} unidades vendidas "
                    f"({100 * fora / total:.0f}%) ficaram fora do plano. Combos sem "
                    "sabor identificado ficam de fora porque o relatório do iFood não "
                    "informa quais salgados o cliente escolheu."
                )
            st.dataframe(
                classificacao.sort_values(["Tratamento", "Quantidade"], ascending=[True, False]),
                use_container_width=True, hide_index=True,
            )

with aba2:
    st.subheader("Peso de cada dia da semana")
    st.caption(
        "Índice = média de pedidos daquele dia dividida pela média geral. "
        "Acima de 1,00 o dia vende mais que a média; abaixo, vende menos."
    )
    grafico = sazonalidade.set_index("Dia")["Índice de sazonalidade"]
    st.bar_chart(grafico)

    mostrar = sazonalidade.copy()
    mostrar["Índice de sazonalidade"] = mostrar["Índice de sazonalidade"].round(3)
    mostrar["Média de pedidos/dia"] = mostrar["Média de pedidos/dia"].round(1)
    if mapa_datas:
        mostrar.insert(
            1, "Data (próxima semana)",
            mostrar["Dia"].astype(str).map(lambda d: mapa_datas.get(d, "")).map(
                lambda dt: dt.strftime("%d/%m") if dt else ""
            ),
        )
    st.dataframe(mostrar, use_container_width=True, hide_index=True)

    ausentes = [d for d in DIAS_SEMANA if d not in colunas_dia]
    if ausentes:
        st.info(
            f"Sem vendas registradas em: {', '.join(ausentes)}. "
            "Esses dias foram tratados como fechados e não entram na média diária."
        )

with aba3:
    st.subheader("Itens mais vendidos no período")
    ranking = (
        itens.groupby("item", as_index=False)["quantidade"].sum()
        .sort_values("quantidade", ascending=False)
    )
    ranking["Participação %"] = (
        100 * ranking["quantidade"] / ranking["quantidade"].sum()
    ).round(1)
    ranking["Acumulado %"] = ranking["Participação %"].cumsum().round(1)
    ranking = ranking.rename(columns={"item": "Item", "quantidade": "Quantidade"})

    st.bar_chart(ranking.head(15).set_index("Item")["Quantidade"])

    curva_a = ranking[ranking["Acumulado %"] <= 80]
    st.caption(
        f"Curva ABC: {len(curva_a)} itens respondem por cerca de 80% do volume. "
        "São eles que merecem controle mais rigoroso de produção."
    )
    st.dataframe(ranking, use_container_width=True, hide_index=True)

with aba4:
    st.subheader("Erro do modelo")

    # A validação usa o histórico completo (não só os períodos marcados na
    # barra lateral), para ter o maior número possível de rodadas. A regra
    # de previsão é a mesma do plano: últimos N períodos.
    hist_itens = base_itens
    hist_dias = st.session_state.dias
    total_periodos = len(ordenar_periodos(hist_itens))

    evolucao = validar_historico(hist_itens, hist_dias, janela=n_recentes)

    if evolucao.empty:
        st.info(
            "Envie pelo menos dois períodos diferentes para que a ferramenta "
            "possa comparar a previsão com o que realmente aconteceu."
        )
    else:
        ultima = evolucao.iloc[-1]
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("MAPE geral (última rodada)", f"{ultima['MAPE geral (%)']:.1f}%")
        col_b.metric("MAPE dos 10 mais vendidos (última rodada)",
                     f"{ultima['MAPE top 10 (%)']:.1f}%")
        col_c.metric("Rodadas de validação", len(evolucao))
        st.caption(
            f"Cada rodada usa até os {n_recentes} período(s) anteriores ao período "
            "testado — a mesma regra do plano de produção — para prever esse "
            "período, e compara com o que realmente foi vendido. Itens de giro "
            "alto costumam ter erro bem menor que a média, porque itens raros "
            "oscilam muito em termos percentuais."
        )

        if len(evolucao) >= 2:
            st.markdown("#### Evolução do erro conforme o histórico cresce")
            st.line_chart(
                evolucao.set_index("Rodada")[["MAPE geral (%)", "MAPE top 10 (%)"]]
            )
        st.dataframe(evolucao, use_container_width=True, hide_index=True)

        st.markdown("#### Detalhe por item — última rodada")
        detalhe = validar_modelo(hist_itens, hist_dias, janela=n_recentes)
        st.dataframe(detalhe.round(1), use_container_width=True, hide_index=True)

        if total_periodos >= 3:
            with st.expander("Quantos períodos recentes prevêem melhor?"):
                candidatas = [j for j in (2, 4, 8, 12) if j < total_periodos] + [None]
                tabela_janelas = comparar_janelas(hist_itens, hist_dias, candidatas)
                st.dataframe(tabela_janelas, use_container_width=True, hide_index=True)
                if not tabela_janelas.empty:
                    vencedora = tabela_janelas.loc[
                        tabela_janelas["MAPE top 10 médio (%)"].idxmin()
                    ]
                    st.caption(
                        f"Menor erro nos 10 itens mais vendidos: **{vencedora['Janela']}** "
                        f"({vencedora['MAPE top 10 médio (%)']:.1f}%). Todas as opções "
                        "são testadas nos mesmos períodos, então a comparação é justa. "
                        "Use esse valor no controle 'Usar os últimos N períodos'."
                    )

with st.expander("Como a previsão é calculada"):
    st.markdown(
        """
Quatro passos, todos a partir dos relatórios enviados:

**1. Itens de produção.** Combos com um salgado identificado (por exemplo,
"Coxinha + Suco") são somados a esse salgado. Bebidas e combos que não dizem
qual salgado vem dentro ficam fora do plano. Pode ser desligado na barra lateral.

**2. Dias de operação.** A partir do texto do período que aparece no relatório
enviado, a ferramenta conta quantas vezes cada dia da semana ocorreu. Dias sem
nenhuma venda são tratados como fechados e removidos da conta, para não
derrubar a média.

**3. Índice de sazonalidade de cada dia.**

    índice(dia) = (pedidos do dia / ocorrências do dia) ÷ (total de pedidos / dias operados)

**4. Previsão por item.**

    média diária(item) = quantidade vendida nos últimos N períodos / dias operados
    previsão(item, dia) = média diária(item) × índice(dia) × (1 + margem)

Só os últimos N períodos entram no cálculo (média móvel), para que a previsão
acompanhe mudanças recentes nas vendas. O valor de N é escolhido na barra
lateral, e a aba Validação mostra qual N erra menos.

A divisão pelas ocorrências no passo 3 importa: quando os períodos enviados
têm tamanhos diferentes, um dia da semana pode aparecer mais vezes que outro,
e sem esse ajuste ele pareceria vender mais do que realmente vende.
        """
    )
