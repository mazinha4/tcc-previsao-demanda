"""
Motor de cálculo da ferramenta de planejamento de produção.

Contém apenas lógica pura (leitura dos relatórios, sazonalidade, previsão,
validação e o merge do histórico). Não depende do Streamlit nem de onde o
histórico é guardado — isso fica a cargo de persistencia.py — o que permite
testar por fora da interface e trocar de armazenamento sem mexer aqui.
"""

import unicodedata
from datetime import datetime, timedelta

import pandas as pd

# --------------------------------------------------------------------------
# Configuração geral
# --------------------------------------------------------------------------

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MAPA_WEEKDAY = {i: d for i, d in enumerate(DIAS_SEMANA)}

COLUNAS_ITENS = ["periodo", "inicio", "fim", "loja", "item", "quantidade"]
COLUNAS_DIAS = ["periodo", "inicio", "fim", "dia", "pedidos"]


# --------------------------------------------------------------------------
# Utilidades de leitura
# --------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Remove acentos, espaços extras e caixa, para comparar nomes de coluna."""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def achar_coluna(df: pd.DataFrame, *pistas: str) -> str:
    """Localiza a coluna cujo nome contém todas as pistas informadas.

    O iFood muda o cabeçalho dos relatórios de tempos em tempos, então a busca
    é por trecho do nome em vez de igualdade exata.
    """
    for coluna in df.columns:
        alvo = normalizar(coluna)
        if all(normalizar(p) in alvo for p in pistas):
            return coluna
    raise KeyError(
        f"Não encontrei uma coluna contendo {pistas}. "
        f"Colunas disponíveis: {list(df.columns)}"
    )


def achar_aba(arquivo, *pistas: str) -> str:
    """Localiza a aba cujo nome contém as pistas informadas."""
    abas = pd.ExcelFile(arquivo).sheet_names
    for aba in abas:
        alvo = normalizar(aba)
        if all(normalizar(p) in alvo for p in pistas):
            return aba
    raise KeyError(f"Não encontrei a aba {pistas}. Abas disponíveis: {abas}")


def interpretar_periodo(texto: str):
    """Converte '12/06/2026 - 12/08/2026' em (data_inicial, data_final)."""
    partes = str(texto).split("-")
    if len(partes) != 2:
        raise ValueError(f"Período em formato inesperado: {texto}")
    inicio = datetime.strptime(partes[0].strip(), "%d/%m/%Y").date()
    fim = datetime.strptime(partes[1].strip(), "%d/%m/%Y").date()
    return inicio, fim


def contar_ocorrencias(inicio, fim) -> dict:
    """Conta quantas vezes cada dia da semana aparece dentro do período.

    Necessário porque um período de 62 dias pode ter 9 quartas e 8 quintas.
    Sem isso, o índice de sazonalidade fica distorcido.
    """
    ocorrencias = {d: 0 for d in DIAS_SEMANA}
    data = inicio
    while data <= fim:
        ocorrencias[MAPA_WEEKDAY[data.weekday()]] += 1
        data += timedelta(days=1)
    return ocorrencias


def calcular_proxima_semana(itens: pd.DataFrame):
    """Data de início e fim da semana que está sendo prevista.

    O início é o dia seguinte à última data registrada no histórico
    selecionado; o fim é seis dias depois (uma semana completa). Se o
    usuário enviou dados até 21/09, a previsão passa a ser sobre
    22/09 a 28/09.
    """
    if itens.empty:
        return None, None
    ultima_data = itens["fim"].max()
    inicio = ultima_data + timedelta(days=1)
    fim = inicio + timedelta(days=6)
    return inicio, fim


def mapear_dias_para_datas(inicio) -> dict:
    """Mapeia cada dia da semana (Segunda..Domingo) para a data real dentro
    da janela de 7 dias que começa em `inicio`.
    """
    mapa = {}
    data = inicio
    for _ in range(7):
        mapa[MAPA_WEEKDAY[data.weekday()]] = data
        data += timedelta(days=1)
    return mapa


# --------------------------------------------------------------------------
# Leitura dos dois relatórios
# --------------------------------------------------------------------------

def ler_relatorio_cardapio(arquivo) -> pd.DataFrame:
    """Lê a aba 'Itens' do relatório de cardápio.

    Retorna: periodo | inicio | fim | loja | item | quantidade
    """
    aba = achar_aba(arquivo, "iten")
    bruto = pd.read_excel(arquivo, sheet_name=aba)

    col_periodo = achar_coluna(bruto, "periodo")
    col_item = achar_coluna(bruto, "nome", "item")
    col_qtd = achar_coluna(bruto, "vendas total", "quantidade")
    try:
        col_loja = achar_coluna(bruto, "nome da loja")
    except KeyError:
        col_loja = None

    df = pd.DataFrame({
        "periodo": bruto[col_periodo].astype(str).str.strip(),
        "item": bruto[col_item].astype(str).str.strip(),
        "quantidade": pd.to_numeric(bruto[col_qtd], errors="coerce").fillna(0),
        "loja": bruto[col_loja] if col_loja else "—",
    })
    df = df[df["item"].ne("") & df["item"].ne("nan")]

    datas = df["periodo"].map(interpretar_periodo)
    df["inicio"] = datas.map(lambda x: x[0])
    df["fim"] = datas.map(lambda x: x[1])

    # Um mesmo item pode aparecer em mais de uma linha (categorias diferentes).
    df = (
        df.groupby(["periodo", "inicio", "fim", "loja", "item"], as_index=False)
          ["quantidade"].sum()
    )
    return df


def ler_relatorio_vendas(arquivo) -> pd.DataFrame:
    """Lê a aba 'Dias com mais vendas' do relatório de vendas.

    Soma os pedidos das diferentes logísticas (entrega própria + retirada).
    Retorna: periodo | inicio | fim | dia | pedidos
    """
    aba = achar_aba(arquivo, "dias", "vendas")
    bruto = pd.read_excel(arquivo, sheet_name=aba)

    col_periodo = achar_coluna(bruto, "periodo")
    col_dia = achar_coluna(bruto, "dias")
    col_ped = achar_coluna(bruto, "total de vendas")

    df = pd.DataFrame({
        "periodo": bruto[col_periodo].astype(str).str.strip(),
        "dia": bruto[col_dia].astype(str).str.strip().str.capitalize(),
        "pedidos": pd.to_numeric(bruto[col_ped], errors="coerce").fillna(0),
    })
    df["dia"] = df["dia"].replace({
        "Sabado": "Sábado", "Terca": "Terça", "Sexta-feira": "Sexta",
    })
    df = df[df["dia"].isin(DIAS_SEMANA)]

    df = df.groupby(["periodo", "dia"], as_index=False)["pedidos"].sum()

    datas = df["periodo"].map(interpretar_periodo)
    df["inicio"] = datas.map(lambda x: x[0])
    df["fim"] = datas.map(lambda x: x[1])
    return df


# --------------------------------------------------------------------------
# Merge do histórico
# --------------------------------------------------------------------------

def incorporar(historico: pd.DataFrame, novo: pd.DataFrame) -> pd.DataFrame:
    """Adiciona o novo envio ao histórico, substituindo períodos repetidos.

    Evita que o usuário conte a mesma semana duas vezes se subir o arquivo
    de novo por engano.
    """
    if historico.empty:
        return novo.copy()
    periodos_novos = set(novo["periodo"])
    mantido = historico[~historico["periodo"].isin(periodos_novos)]
    return pd.concat([mantido, novo], ignore_index=True)


def encontrar_sobreposicoes(historico: pd.DataFrame, novo: pd.DataFrame) -> list:
    """Encontra períodos que se sobrepõem em datas sem serem o mesmo período.

    O relatório do iFood só dá a quantidade agregada de um período inteiro,
    não por dia. Então, se duas janelas de datas se cruzam (ex.: uma vai até
    12/09 e outra começa em 10/09), os dias 10, 11 e 12 seriam contados duas
    vezes na soma — e não tem como corrigir isso automaticamente, porque não
    dá para saber quanto desses dias pertence a cada envio. Por isso, esse
    tipo de sobreposição é bloqueado, e não apenas substituído como quando o
    período é exatamente igual.

    Retorna uma lista de tuplas (periodo_existente, periodo_novo,
    inicio_conflito, fim_conflito) para cada par que colide.
    """
    if historico.empty:
        return []

    existentes = historico[["periodo", "inicio", "fim"]].drop_duplicates()
    novos = novo[["periodo", "inicio", "fim"]].drop_duplicates()

    conflitos = []
    for _, ex in existentes.iterrows():
        for _, nv in novos.iterrows():
            if ex["periodo"] == nv["periodo"]:
                continue  # mesmo período = reenvio normal, não é sobreposição
            inicio_conflito = max(ex["inicio"], nv["inicio"])
            fim_conflito = min(ex["fim"], nv["fim"])
            if inicio_conflito <= fim_conflito:
                conflitos.append((ex["periodo"], nv["periodo"], inicio_conflito, fim_conflito))
    return conflitos


# --------------------------------------------------------------------------
# Motor de cálculo
# --------------------------------------------------------------------------

def calcular_sazonalidade(dias: pd.DataFrame):
    """Índice de sazonalidade de cada dia da semana.

        indice_d = (pedidos_d / ocorrencias_d) / (total_pedidos / dias_operados)

    Um índice de 1,30 na quarta significa que a quarta vende 30% acima da
    média de um dia qualquer de operação.
    """
    pedidos = {d: 0.0 for d in DIAS_SEMANA}
    ocorrencias = {d: 0 for d in DIAS_SEMANA}

    for periodo, bloco in dias.groupby("periodo"):
        inicio, fim = bloco["inicio"].iloc[0], bloco["fim"].iloc[0]
        occ_periodo = contar_ocorrencias(inicio, fim)
        dias_com_venda = set(bloco.loc[bloco["pedidos"] > 0, "dia"])
        for d in dias_com_venda:
            pedidos[d] += float(bloco.loc[bloco["dia"] == d, "pedidos"].sum())
            ocorrencias[d] += occ_periodo[d]

    operantes = [d for d in DIAS_SEMANA if ocorrencias[d] > 0]
    dias_operados = sum(ocorrencias[d] for d in operantes)
    total_pedidos = sum(pedidos[d] for d in operantes)

    if dias_operados == 0 or total_pedidos == 0:
        return pd.DataFrame(), 0, 0

    media_geral = total_pedidos / dias_operados
    tabela = pd.DataFrame({
        "Dia": operantes,
        "Pedidos no período": [pedidos[d] for d in operantes],
        "Ocorrências do dia": [ocorrencias[d] for d in operantes],
        "Média de pedidos/dia": [pedidos[d] / ocorrencias[d] for d in operantes],
    })
    tabela["Índice de sazonalidade"] = tabela["Média de pedidos/dia"] / media_geral
    tabela["Dia"] = pd.Categorical(tabela["Dia"], categories=DIAS_SEMANA, ordered=True)
    return tabela.sort_values("Dia").reset_index(drop=True), dias_operados, total_pedidos


def calcular_previsao(itens: pd.DataFrame, sazonalidade: pd.DataFrame,
                      dias_operados: int, margem: float = 0.0) -> pd.DataFrame:
    """Previsão por item e por dia da semana.

        media_diaria_item = quantidade_total / dias_operados
        previsao(item, dia) = media_diaria_item * indice_do_dia * (1 + margem)

    Usa apenas os períodos que chegam em `itens` — na interface, são os
    últimos N períodos escolhidos pelo usuário (média móvel).
    """
    totais = itens.groupby("item", as_index=False)["quantidade"].sum()
    totais["media_diaria"] = totais["quantidade"] / dias_operados

    linhas = []
    for _, item in totais.iterrows():
        linha = {"Item": item["item"], "Média diária": item["media_diaria"]}
        for _, dia in sazonalidade.iterrows():
            valor = item["media_diaria"] * dia["Índice de sazonalidade"] * (1 + margem)
            linha[str(dia["Dia"])] = valor
        linhas.append(linha)

    previsao = pd.DataFrame(linhas)
    colunas_dia = [str(d) for d in sazonalidade["Dia"]]
    previsao["Total da semana"] = previsao[colunas_dia].sum(axis=1)
    return previsao.sort_values("Total da semana", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# Validação (backtest)
# --------------------------------------------------------------------------

def ordenar_periodos(itens: pd.DataFrame) -> list:
    """Lista dos períodos do histórico, do mais antigo para o mais recente."""
    if itens.empty:
        return []
    return (
        itens[["periodo", "inicio"]].drop_duplicates()
        .sort_values("inicio")["periodo"].tolist()
    )


def _comparar_periodo(itens: pd.DataFrame, dias: pd.DataFrame,
                      treino: list, teste: str) -> pd.DataFrame:
    """Prevê o período `teste` usando apenas os períodos em `treino` e
    compara com o que realmente foi vendido, item a item.

    A comparação é feita em "unidades por semana", para que períodos de
    tamanhos diferentes (ex.: um bloco de 2 meses e uma semana) possam ser
    comparados. A margem de segurança NÃO entra aqui: mede-se o modelo puro.
    """
    saz, dias_op, _ = calcular_sazonalidade(dias[dias["periodo"].isin(treino)])
    if saz.empty:
        return pd.DataFrame()

    media_diaria = (
        itens[itens["periodo"].isin(treino)].groupby("item")["quantidade"].sum()
        / dias_op
    )
    previsto_semana = media_diaria * saz["Índice de sazonalidade"].sum()

    _, dias_op_teste, _ = calcular_sazonalidade(dias[dias["periodo"] == teste])
    if dias_op_teste == 0:
        return pd.DataFrame()
    semanas_teste = dias_op_teste / len(saz)
    real_semana = (
        itens[itens["periodo"] == teste].groupby("item")["quantidade"].sum()
        / semanas_teste
    )

    comparacao = pd.DataFrame({
        "Previsto (semana)": previsto_semana,
        "Real (semana)": real_semana,
    }).dropna()
    comparacao = comparacao[comparacao["Real (semana)"] > 0]
    if comparacao.empty:
        return pd.DataFrame()

    comparacao["Erro absoluto"] = (
        comparacao["Previsto (semana)"] - comparacao["Real (semana)"]
    ).abs()
    comparacao["Erro %"] = 100 * comparacao["Erro absoluto"] / comparacao["Real (semana)"]
    comparacao = comparacao.sort_values("Real (semana)", ascending=False)
    comparacao.index.name = "Item"
    return comparacao.reset_index()


def _periodos_de_treino(periodos: list, k: int, janela) -> list:
    """Períodos usados para prever o período de índice k.

    janela=None usa todos os anteriores; janela=N usa só os N mais recentes.
    """
    inicio = 0 if janela is None else max(0, k - janela)
    return periodos[inicio:k]


def validar_modelo(itens: pd.DataFrame, dias: pd.DataFrame, janela=1) -> pd.DataFrame:
    """Detalhe por item da ÚLTIMA rodada: prevê o período mais recente
    usando os `janela` períodos anteriores a ele.

    janela=1 reproduz o comportamento antigo (penúltimo prevê o último).
    """
    periodos = ordenar_periodos(itens)
    if len(periodos) < 2:
        return pd.DataFrame()
    k = len(periodos) - 1
    treino = _periodos_de_treino(periodos, k, janela)
    return _comparar_periodo(itens, dias, treino, periodos[k])


def validar_historico(itens: pd.DataFrame, dias: pd.DataFrame, janela=None) -> pd.DataFrame:
    """Validação com janela móvel ao longo de todo o histórico.

    Para cada período k (a partir do segundo), usa os períodos anteriores
    a ele — todos, ou só os `janela` mais recentes — para prever o período
    k, exatamente como o plano de produção faria naquele momento. Assim dá
    para ver se o erro diminui à medida que o histórico cresce.

    Retorna uma linha por rodada.
    """
    periodos = ordenar_periodos(itens)
    rodadas = []
    for k in range(1, len(periodos)):
        treino = _periodos_de_treino(periodos, k, janela)
        teste = periodos[k]
        comparacao = _comparar_periodo(itens, dias, treino, teste)
        if comparacao.empty:
            continue
        rodadas.append({
            "Rodada": len(rodadas) + 1,
            "Período testado": teste,
            "Períodos no treino": len(treino),
            "MAPE geral (%)": round(comparacao["Erro %"].mean(), 1),
            "MAPE top 10 (%)": round(comparacao.head(10)["Erro %"].mean(), 1),
            "Itens comparados": len(comparacao),
        })
    return pd.DataFrame(rodadas)


def comparar_janelas(itens: pd.DataFrame, dias: pd.DataFrame, janelas: list) -> pd.DataFrame:
    """Roda a validação para cada tamanho de janela e resume o erro médio.

    Todas as janelas são testadas nos mesmos períodos, então a comparação é
    justa. Responde à pergunta: quantos períodos recentes prevêem melhor?
    """
    linhas = []
    for janela in janelas:
        evolucao = validar_historico(itens, dias, janela)
        if evolucao.empty:
            continue
        linhas.append({
            "Janela": "Todo o histórico" if janela is None else f"Últimos {janela} períodos",
            "Rodadas": len(evolucao),
            "MAPE geral médio (%)": round(evolucao["MAPE geral (%)"].mean(), 1),
            "MAPE top 10 médio (%)": round(evolucao["MAPE top 10 (%)"].mean(), 1),
        })
    return pd.DataFrame(linhas)
