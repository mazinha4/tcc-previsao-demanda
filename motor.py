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


def validar_modelo(itens: pd.DataFrame, dias: pd.DataFrame) -> pd.DataFrame:
    """Backtest: usa o penúltimo envio para prever o último e mede o erro.

    Reporta o MAPE (erro percentual absoluto médio) por item.
    """
    periodos = (
        itens[["periodo", "inicio"]].drop_duplicates()
        .sort_values("inicio")["periodo"].tolist()
    )
    if len(periodos) < 2:
        return pd.DataFrame()

    treino, teste = periodos[-2], periodos[-1]

    saz_treino, dias_op_treino, _ = calcular_sazonalidade(dias[dias["periodo"] == treino])
    if saz_treino.empty:
        return pd.DataFrame()

    itens_treino = itens[itens["periodo"] == treino]
    soma_indices = saz_treino["Índice de sazonalidade"].sum()
    media_treino = (
        itens_treino.groupby("item")["quantidade"].sum() / dias_op_treino
    )
    previsto_semana = media_treino * soma_indices

    bloco_teste = dias[dias["periodo"] == teste]
    _, dias_op_teste, _ = calcular_sazonalidade(bloco_teste)
    semanas_teste = dias_op_teste / len(saz_treino) if len(saz_treino) else 0
    real_semana = (
        itens[itens["periodo"] == teste].groupby("item")["quantidade"].sum()
        / max(semanas_teste, 1e-9)
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
