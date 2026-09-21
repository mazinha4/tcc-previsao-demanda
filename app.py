"""
Ferramenta de apoio a decisao para planejamento da producao de restaurantes
a partir dos relatorios do iFood (Portal do Parceiro).

Este arquivo cuida apenas da interface. Toda a logica de calculo esta em
motor.py.

Execucao local:
    pip install -r requirements.txt
    streamlit run app.py
"""

import math
import os

import streamlit as st

from motor import (
    ARQ_DIAS,
    ARQ_ITENS,
    DIAS_SEMANA,
    calcular_previsao,
    calcular_sazonalidade,
    carregar_historico,
    incorporar,
    ler_relatorio_cardapio,
    ler_relatorio_vendas,
    salvar_historico,
    validar_modelo,
)

st.set_page_config(
    page_title="Planejamento de Producao | iFood",
    page_icon="\U0001F4CA",
    layout="wide",
)

# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------

st.title("📊 Planejamento de producao a partir das vendas do iFood")
st.caption(
    "Envie os relatorios exportados do Portal do Parceiro para obter a "
    "previsao de quanto produzir de cada item em cada dia da semana."
)

if "itens" not in st.session_state:
    st.session_state.itens, st.session_state.dias = carregar_historico()

with st.sidebar:
    st.header("1. Enviar relatorios")
    arq_cardapio = st.file_uploader(
        "Relatorio de cardapio (.xlsx)", type=["xlsx", "xls"],
        help="Portal do Parceiro › Analise › Cardapio. Usa a aba 'Itens'.",
    )
    arq_vendas = st.file_uploader(
        "Relatorio de vendas (.xlsx)", type=["xlsx", "xls"],
        help="Portal do Parceiro › Analise › Vendas. Usa a aba 'Dias com mais vendas'.",
    )

    if st.button("Processar e salvar no historico", type="primary",
                 use_container_width=True, disabled=not (arq_cardapio and arq_vendas)):
        try:
            novos_itens = ler_relatorio_cardapio(arq_cardapio)
            novos_dias = ler_relatorio_vendas(arq_vendas)

            if set(novos_itens["periodo"]) != set(novos_dias["periodo"]):
                st.warning(
                    "Os dois relatorios sao de periodos diferentes: "
                    f"{sorted(set(novos_itens['periodo']))} e "
                    f"{sorted(set(novos_dias['periodo']))}. "
                    "Confira antes de confiar na previsao."
                )

            st.session_state.itens = incorporar(st.session_state.itens, novos_itens)
            st.session_state.dias = incorporar(st.session_state.dias, novos_dias)
            salvar_historico(st.session_state.itens, st.session_state.dias)
            st.success(f"Periodo {novos_itens['periodo'].iloc[0]} registrado.")
        except Exception as erro:
            st.error(f"Nao consegui ler o arquivo: {erro}")

    st.divider()
    st.header("2. Parametros")
    margem = st.slider(
        "Margem de seguranca (%)", 0, 50, 10,
        help="Producao extra sobre a previsao para reduzir risco de ruptura.",
    ) / 100

    arredondar = st.checkbox("Arredondar para cima (unidades inteiras)", value=True)

    st.divider()
    st.header("3. Historico")
    if not st.session_state.itens.empty:
        disponiveis = (
            st.session_state.itens[["periodo", "inicio"]].drop_duplicates()
            .sort_values("inicio")["periodo"].tolist()
        )
        selecionados = st.multiselect(
            "Periodos usados no calculo", disponiveis, default=disponiveis,
        )
        if st.button("Limpar todo o historico", use_container_width=True):
            for caminho in (ARQ_ITENS, ARQ_DIAS):
                if os.path.exists(caminho):
                    os.remove(caminho)
            st.session_state.itens, st.session_state.dias = carregar_historico()
            st.rerun()
    else:
        selecionados = []

# --------------------------------------------------------------------------

if st.session_state.itens.empty:
    st.info(
        "Nenhum dado carregado ainda. Envie os dois relatorios na barra lateral "
        "para comecar."
    )
    st.stop()

itens = st.session_state.itens[st.session_state.itens["periodo"].isin(selecionados)]
dias = st.session_state.dias[st.session_state.dias["periodo"].isin(selecionados)]

if itens.empty or dias.empty:
    st.warning("Selecione ao menos um periodo na barra lateral.")
    st.stop()

sazonalidade, dias_operados, total_pedidos = calcular_sazonalidade(dias)
if sazonalidade.empty:
    st.error("Nao ha pedidos suficientes nos periodos selecionados.")
    st.stop()

previsao = calcular_previsao(itens, sazonalidade, dias_operados, margem)
colunas_dia = [str(d) for d in sazonalidade["Dia"]]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Dias de operacao analisados", dias_operados)
c2.metric("Pedidos no periodo", f"{int(total_pedidos):,}".replace(",", "."))
c3.metric("Itens no cardapio", itens["item"].nunique())
melhor = sazonalidade.loc[sazonalidade["Indice de sazonalidade"].idxmax()]
c4.metric(
    "Dia mais forte", str(melhor["Dia"]),
    f"{(melhor['Indice de sazonalidade'] - 1) * 100:+.0f}% vs. media",
)

aba1, aba2, aba3, aba4 = st.tabs([
    "🍽️ Producao da semana", "📅 Sazonalidade", "📈 Ranking de itens", "✅ Validacao",
])

with aba1:
    st.subheader("Quanto produzir de cada item, por dia da semana")
    if margem:
        st.caption(f"Valores ja incluem margem de seguranca de {margem:.0%}.")

    quantos = st.number_input(
        "Mostrar os N itens mais vendidos", 5, max(5, len(previsao)),
        min(20, len(previsao)), step=5,
    )
    tabela = previsao.head(int(quantos)).copy()

    exibir = tabela[["Item"] + colunas_dia + ["Total da semana"]].copy()
    if arredondar:
        for coluna in colunas_dia + ["Total da semana"]:
            exibir[coluna] = exibir[coluna].map(lambda v: int(math.ceil(v)))
    else:
        for coluna in colunas_dia + ["Total da semana"]:
            exibir[coluna] = exibir[coluna].round(1)

    st.dataframe(
        exibir.style.background_gradient(cmap="Oranges", subset=colunas_dia),
        use_container_width=True, hide_index=True,
    )

    st.download_button(
        "⬇️ Baixar plano de producao (CSV)",
        exibir.to_csv(index=False).encode("utf-8-sig"),
        file_name="plano_producao_semanal.csv",
        mime="text/csv",
    )

    dia_escolhido = st.selectbox("Ver lista de producao de um dia especifico", colunas_dia)
    lista = tabela[["Item", dia_escolhido]].copy()
    lista = lista[lista[dia_escolhido] > 0].rename(columns={dia_escolhido: "Produzir"})
    if arredondar:
        lista["Produzir"] = lista["Produzir"].map(lambda v: int(math.ceil(v)))
    else:
        lista["Produzir"] = lista["Produzir"].round(1)
    st.dataframe(lista, use_container_width=True, hide_index=True)

with aba2:
    st.subheader("Peso de cada dia da semana")
    st.caption(
        "Indice = media de pedidos daquele dia dividida pela media geral. "
        "Acima de 1,00 o dia vende mais que a media; abaixo, vende menos."
    )
    grafico = sazonalidade.set_index("Dia")["Indice de sazonalidade"]
    st.bar_chart(grafico)

    mostrar = sazonalidade.copy()
    mostrar["Indice de sazonalidade"] = mostrar["Indice de sazonalidade"].round(3)
    mostrar["Media de pedidos/dia"] = mostrar["Media de pedidos/dia"].round(1)
    st.dataframe(mostrar, use_container_width=True, hide_index=True)

    ausentes = [d for d in DIAS_SEMANA if d not in colunas_dia]
    if ausentes:
        st.info(
            f"Sem vendas registradas em: {', '.join(ausentes)}. "
            "Esses dias foram tratados como fechados e nao entram na media diaria."
        )

with aba3:
    st.subheader("Itens mais vendidos no periodo")
    ranking = (
        itens.groupby("item", as_index=False)["quantidade"].sum()
        .sort_values("quantidade", ascending=False)
    )
    ranking["Participacao %"] = (
        100 * ranking["quantidade"] / ranking["quantidade"].sum()
    ).round(1)
    ranking["Acumulado %"] = ranking["Participacao %"].cumsum().round(1)
    ranking = ranking.rename(columns={"item": "Item", "quantidade": "Quantidade"})

    st.bar_chart(ranking.head(15).set_index("Item")["Quantidade"])

    curva_a = ranking[ranking["Acumulado %"] <= 80]
    st.caption(
        f"Curva ABC: {len(curva_a)} itens respondem por cerca de 80% do volume. "
        "Sao eles que merecem controle mais rigoroso de producao."
    )
    st.dataframe(ranking, use_container_width=True, hide_index=True)

with aba4:
    st.subheader("Erro do modelo")
    resultado = validar_modelo(itens, dias)
    if resultado.empty:
        st.info(
            "Envie pelo menos dois periodos diferentes para que a ferramenta "
            "possa comparar a previsao com o que realmente aconteceu."
        )
    else:
        mape = resultado["Erro %"].mean()
        principais = resultado.head(10)["Erro %"].mean()
        col_a, col_b = st.columns(2)
        col_a.metric("MAPE geral", f"{mape:.1f}%")
        col_b.metric("MAPE dos 10 mais vendidos", f"{principais:.1f}%")
        st.caption(
            "O periodo anterior foi usado para prever o mais recente. "
            "Itens de giro alto costumam ter erro bem menor que a media, "
            "porque itens raros oscilam muito em termos percentuais."
        )
        st.dataframe(
            resultado.round(1), use_container_width=True, hide_index=True,
        )

with st.expander("Como a previsao e calculada"):
    st.markdown(
        """
Tres passos, todos a partir dos dois relatorios enviados:

**1. Dias de operacao.** A partir do texto do periodo (`12/06/2026 - 12/08/2026`)
a ferramenta conta quantas vezes cada dia da semana ocorreu. Dias sem nenhuma
venda sao tratados como fechados e removidos da conta, para nao derrubar a media.

**2. Indice de sazonalidade de cada dia.**

    indice(dia) = (pedidos do dia / ocorrencias do dia) ÷ (total de pedidos / dias operados)

**3. Previsao por item.**

    media diaria(item) = quantidade vendida no periodo / dias operados
    previsao(item, dia) = media diaria(item) × indice(dia) × (1 + margem)

A divisao pelas ocorrencias no passo 2 importa: num periodo de dois meses pode
haver 9 quartas e 8 quintas, e sem esse ajuste a quinta pareceria vender menos
do que realmente vende.
        """
    )
