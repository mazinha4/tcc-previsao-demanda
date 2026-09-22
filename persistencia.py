"""
Persistência do histórico de vendas, com isolamento por restaurante.

Vários restaurantes podem usar o mesmo app. Cada um cria uma conta simples
(nome do restaurante + senha) na primeira vez e, a partir daí, só entra com
essas credenciais. Por trás, todos os restaurantes compartilham a mesma
planilha do Google, mas cada linha é marcada com o restaurante dono — a
leitura e a escrita sempre filtram por esse identificador, então um
restaurante nunca vê o histórico do outro.

Por que Google Sheets: o Streamlit Community Cloud não garante que o disco
do app sobrevive entre reinicializações — se o app ficar um tempo sem uso e
"dormir", um histórico em CSV local seria apagado. A planilha existe fora do
servidor do Streamlit e não é apagada.

Rodando localmente sem configurar o Google, o app cai para um CSV local em
dados/ — útil para testar rápido, e a lógica de multi-restaurante funciona
igual nos dois casos.
"""

import hashlib
import os
import re
import secrets as secrets_lib

import pandas as pd
import streamlit as st

from motor import COLUNAS_DIAS, COLUNAS_ITENS, normalizar

PASTA_DADOS = "dados"
ARQ_ITENS = os.path.join(PASTA_DADOS, "historico_itens.csv")
ARQ_DIAS = os.path.join(PASTA_DADOS, "historico_dias.csv")
ARQ_USUARIOS = os.path.join(PASTA_DADOS, "usuarios.csv")

ABA_ITENS = "historico_itens"
ABA_DIAS = "historico_dias"
ABA_USUARIOS = "usuarios"

COLUNAS_ITENS_ARM = COLUNAS_ITENS + ["restaurante"]
COLUNAS_DIAS_ARM = COLUNAS_DIAS + ["restaurante"]
COLUNAS_USUARIOS = ["restaurante", "nome_exibicao", "salt", "hash"]

ESCOPOS_GOOGLE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _usa_google_sheets() -> bool:
    return "gcp_service_account" in st.secrets and "planilha_url" in st.secrets


def modo_atual() -> str:
    """Só para exibir na interface qual armazenamento está ativo."""
    return "Google Sheets" if _usa_google_sheets() else "CSV local (Google não configurado)"


# --------------------------------------------------------------------------
# Identificador do restaurante e senha
# --------------------------------------------------------------------------

def slugificar(nome: str) -> str:
    """Transforma o nome digitado num identificador estável ('login').

    'Cantina da Vovó 2' -> 'cantina-da-vovo-2'. Isso é o que garante que
    cada restaurante enxergue só o próprio histórico.
    """
    base = normalizar(nome)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base


def _gerar_salt() -> str:
    return secrets_lib.token_hex(16)


def _hash_senha(senha: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(salt), 100_000
    ).hex()


# --------------------------------------------------------------------------
# Acesso genérico às abas (Google Sheets ou CSV)
# --------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _obter_planilha():
    import gspread
    from google.oauth2.service_account import Credentials

    credenciais = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=ESCOPOS_GOOGLE,
    )
    cliente = gspread.authorize(credenciais)
    return cliente.open_by_url(st.secrets["planilha_url"])


def _obter_aba(planilha, nome: str, colunas: list):
    import gspread

    try:
        return planilha.worksheet(nome)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(title=nome, rows=2000, cols=len(colunas) + 2)
        aba.append_row(colunas)
        return aba


def _ler_aba(nome: str, colunas: list) -> pd.DataFrame:
    if _usa_google_sheets():
        planilha = _obter_planilha()
        aba = _obter_aba(planilha, nome, colunas)
        registros = aba.get_all_records()
        if not registros:
            return pd.DataFrame(columns=colunas)
        df = pd.DataFrame(registros)
        for coluna in colunas:
            if coluna not in df.columns:
                df[coluna] = None
        return df[colunas]

    caminho = {
        ABA_ITENS: ARQ_ITENS, ABA_DIAS: ARQ_DIAS, ABA_USUARIOS: ARQ_USUARIOS,
    }[nome]
    if not os.path.exists(caminho):
        return pd.DataFrame(columns=colunas)
    return pd.read_csv(caminho, dtype=str).reindex(columns=colunas)


def _escrever_aba(nome: str, colunas: list, df: pd.DataFrame):
    if _usa_google_sheets():
        planilha = _obter_planilha()
        aba = _obter_aba(planilha, nome, colunas)
        aba.clear()
        corpo = df.copy()
        for coluna in colunas:
            if coluna not in corpo.columns:
                corpo[coluna] = ""
        corpo = corpo[colunas].astype(str)
        aba.update([colunas] + corpo.values.tolist())
        return

    os.makedirs(PASTA_DADOS, exist_ok=True)
    caminho = {
        ABA_ITENS: ARQ_ITENS, ABA_DIAS: ARQ_DIAS, ABA_USUARIOS: ARQ_USUARIOS,
    }[nome]
    df.reindex(columns=colunas).to_csv(caminho, index=False)


def _ajustar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["inicio"] = pd.to_datetime(df["inicio"], errors="coerce").dt.date
    df["fim"] = pd.to_datetime(df["fim"], errors="coerce").dt.date
    for coluna in ("quantidade", "pedidos"):
        if coluna in df.columns:
            df[coluna] = pd.to_numeric(df[coluna], errors="coerce").fillna(0)
    return df


# --------------------------------------------------------------------------
# Contas (cadastro e login)
# --------------------------------------------------------------------------

def criar_conta(nome_exibicao: str, senha: str):
    """Cria a conta de um restaurante novo.

    Retorna (sucesso, mensagem, restaurante_id).
    """
    restaurante_id = slugificar(nome_exibicao)
    if not restaurante_id:
        return False, "Digite um nome de restaurante válido.", None
    if len(senha) < 4:
        return False, "A senha precisa ter ao menos 4 caracteres.", None

    usuarios = _ler_aba(ABA_USUARIOS, COLUNAS_USUARIOS)
    if not usuarios.empty and restaurante_id in usuarios["restaurante"].values:
        return False, "Já existe uma conta com esse nome. Tente entrar em vez de criar.", None

    salt = _gerar_salt()
    nova_linha = pd.DataFrame([{
        "restaurante": restaurante_id,
        "nome_exibicao": nome_exibicao.strip(),
        "salt": salt,
        "hash": _hash_senha(senha, salt),
    }])
    usuarios = pd.concat([usuarios, nova_linha], ignore_index=True)
    _escrever_aba(ABA_USUARIOS, COLUNAS_USUARIOS, usuarios)
    return True, "Conta criada com sucesso.", restaurante_id


def entrar(nome_exibicao: str, senha: str):
    """Autentica um restaurante já cadastrado.

    Retorna (sucesso, mensagem, restaurante_id, nome_exibicao_salvo).
    """
    restaurante_id = slugificar(nome_exibicao)
    usuarios = _ler_aba(ABA_USUARIOS, COLUNAS_USUARIOS)
    if usuarios.empty or restaurante_id not in usuarios["restaurante"].values:
        return False, "Não encontramos essa conta. Crie uma conta primeiro.", None, None

    linha = usuarios[usuarios["restaurante"] == restaurante_id].iloc[0]
    if _hash_senha(senha, linha["salt"]) != linha["hash"]:
        return False, "Senha incorreta.", None, None

    return True, "", restaurante_id, linha["nome_exibicao"]


# --------------------------------------------------------------------------
# Histórico (isolado por restaurante)
# --------------------------------------------------------------------------

def carregar_historico(restaurante_id: str):
    todos_itens = _ajustar_tipos(_ler_aba(ABA_ITENS, COLUNAS_ITENS_ARM))
    todos_dias = _ajustar_tipos(_ler_aba(ABA_DIAS, COLUNAS_DIAS_ARM))

    if todos_itens.empty:
        itens = pd.DataFrame(columns=COLUNAS_ITENS)
    else:
        itens = (
            todos_itens[todos_itens["restaurante"] == restaurante_id]
            .drop(columns=["restaurante"]).reset_index(drop=True)
        )
    if todos_dias.empty:
        dias = pd.DataFrame(columns=COLUNAS_DIAS)
    else:
        dias = (
            todos_dias[todos_dias["restaurante"] == restaurante_id]
            .drop(columns=["restaurante"]).reset_index(drop=True)
        )
    return itens, dias


def salvar_historico(restaurante_id: str, itens: pd.DataFrame, dias: pd.DataFrame):
    """Substitui, na planilha, apenas as linhas deste restaurante.

    Os dados dos demais restaurantes são preservados intactos.
    """
    todos_itens = _ajustar_tipos(_ler_aba(ABA_ITENS, COLUNAS_ITENS_ARM))
    todos_dias = _ajustar_tipos(_ler_aba(ABA_DIAS, COLUNAS_DIAS_ARM))

    novos_itens = itens.copy()
    novos_itens["restaurante"] = restaurante_id
    novos_dias = dias.copy()
    novos_dias["restaurante"] = restaurante_id

    if not todos_itens.empty:
        todos_itens = todos_itens[todos_itens["restaurante"] != restaurante_id]
    if not todos_dias.empty:
        todos_dias = todos_dias[todos_dias["restaurante"] != restaurante_id]

    todos_itens = pd.concat([todos_itens, novos_itens], ignore_index=True)
    todos_dias = pd.concat([todos_dias, novos_dias], ignore_index=True)

    _escrever_aba(ABA_ITENS, COLUNAS_ITENS_ARM, todos_itens)
    _escrever_aba(ABA_DIAS, COLUNAS_DIAS_ARM, todos_dias)
