# Ferramenta de planejamento de produção a partir das vendas do iFood

Aplicação web que recebe os relatórios exportados do Portal do Parceiro iFood e
devolve **quanto produzir de cada item em cada dia da semana**.

O usuário final só vê a interface: envia dois arquivos `.xlsx` e recebe o plano
de produção. Todo o cálculo fica escondido em `motor.py`.

---

## Arquivos

| Arquivo | Função |
|---|---|
| `app.py` | Interface (Streamlit). Login, upload, abas, gráficos, download do plano. |
| `motor.py` | Lógica pura: leitura das planilhas, sazonalidade, previsão, validação, merge do histórico. Não depende do Streamlit. |
| `persistencia.py` | Contas (cadastro/login) e onde o histórico é guardado: Google Sheets se configurado, CSV local como alternativa. |
| `requirements.txt` | Dependências. |
| `dados/` | Histórico em CSV, usado só quando o Google Sheets não está configurado. |

---

## Vários restaurantes, um único app

A ferramenta foi pensada para ser usada por mais de um restaurante ao mesmo
tempo, todos acessando o mesmo link publicado. Cada restaurante:

1. Na primeira vez, cria uma conta na aba **"Criar conta"**: nome do
   restaurante + uma senha.
2. Nas próximas vezes, entra pela aba **"Entrar"** com essas mesmas
   credenciais.

Por trás, todos compartilham a mesma planilha do Google, mas cada linha do
histórico é marcada com o restaurante dono, e toda leitura e escrita filtra
por esse identificador (`persistencia.py`, funções `carregar_historico` e
`salvar_historico`). Um restaurante nunca lê nem sobrescreve o histórico de
outro — testei isso simulando dois restaurantes cadastrando semanas em
paralelo antes de fechar essa versão.

**Sobre a segurança:** a senha nunca é guardada em texto puro — é
transformada com PBKDF2-HMAC-SHA256 (função de hash com "sal" aleatório por
conta) antes de ir para a planilha. É um nível de proteção adequado para um
TCC e para dados de vendas (não é informação sensível como CPF ou cartão),
mas vale declarar no trabalho que não é um sistema de autenticação de nível
produção — não tem recuperação de senha, limite de tentativas, nem HTTPS
garantido pelo lado da aplicação (o Streamlit Cloud já serve por HTTPS).

Separar `motor.py` da interface e do armazenamento não é enfeite: permite
testar o cálculo sem abrir o navegador e trocar de armazenamento (CSV, Google
Sheets, ou futuramente um banco de dados) sem tocar na lógica de previsão. Na
defesa, isso também deixa claro o que é método e o que é implementação.

---

## Armazenamento: Google Sheets (persistente semana após semana)

O Streamlit Community Cloud não garante que o disco do app sobrevive entre
reinicializações — se o app ficar um tempo sem uso e "dormir", um histórico em
CSV local seria apagado. Por isso o histórico é guardado numa planilha do
Google Sheets, que existe fora do servidor do Streamlit e não é apagada nunca.

Rodando localmente na sua máquina, sem configurar nada disso, o app funciona
normalmente e usa CSV local como já fazia antes — útil para testar rápido.

### Passo a passo (a única vez que você precisa fazer isso)

**1. Crie o projeto no Google Cloud**

- Acesse [console.cloud.google.com](https://console.cloud.google.com) e entre
  com sua conta Google normal (não precisa de nada pago).
- No topo, clique em **"Select a project" → "New Project"**. Dê um nome, ex.
  `tcc-previsao-demanda`, e clique em **Create**.

**2. Ative as APIs necessárias**

- Com o projeto selecionado, vá em **APIs e serviços → Biblioteca**
  (ou busque "Google Sheets API" na barra de busca do console).
- Ative a **Google Sheets API**.
- Busque também **Google Drive API** e ative.

**3. Crie a conta de serviço (a "identidade" que o app vai usar)**

- Vá em **APIs e serviços → Credenciais → Criar credenciais → Conta de
  serviço**.
- Dê um nome, ex. `app-tcc`. Pode pular os campos opcionais de permissão.
- Depois de criada, clique nela na lista, vá na aba **Chaves → Adicionar
  chave → Criar nova chave → JSON**. Isso baixa um arquivo `.json` — **guarde
  esse arquivo, ele não pode ser baixado de novo depois.**

**4. Crie a planilha e compartilhe com a conta de serviço**

- Crie uma planilha nova em [sheets.google.com](https://sheets.google.com),
  do jeito que preferir (pode ficar em branco, o app cria as abas sozinho).
- Abra o arquivo `.json` baixado no passo 3 e copie o valor do campo
  `client_email` (algo como
  `app-tcc@tcc-previsao-demanda.iam.gserviceaccount.com`).
- Na planilha, clique em **Compartilhar**, cole esse e-mail e dê permissão de
  **Editor**.
- Copie a URL da planilha (a barra de endereço do navegador).

**5. Configure os "secrets" no Streamlit Cloud**

- No painel do seu app em share.streamlit.io, vá em **Settings → Secrets**.
- Cole o conteúdo abaixo, substituindo pelos valores do seu arquivo `.json` e
  pela URL da sua planilha:

```toml
planilha_url = "https://docs.google.com/spreadsheets/d/SEU_ID_AQUI/edit"

[gcp_service_account]
type = "service_account"
project_id = "cole aqui o project_id do json"
private_key_id = "cole aqui o private_key_id do json"
private_key = "cole aqui o private_key do json, entre aspas, exatamente como está"
client_email = "cole aqui o client_email do json"
client_id = "cole aqui o client_id do json"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "cole aqui o client_x509_cert_url do json"
```

  O campo `private_key` no `.json` já vem com `\n` dentro do texto — copie e
  cole exatamente como está, sem editar nada.

- Clique em **Save**. O Streamlit Cloud reinicia o app sozinho.

**6. Confira que funcionou**

- Abra o app. Na barra lateral, em "3. Histórico", deve aparecer
  **"Armazenamento: Google Sheets"**. Se aparecer "CSV local (Google não
  configurado)", alguma credencial não foi lida — confira se o TOML colado
  em Secrets está sem erro de formatação (aspas, indentação).
- Envie um relatório de teste e confira se duas novas abas (`historico_itens`
  e `historico_dias`) apareceram na sua planilha do Google.

Para rodar localmente com Google Sheets também (em vez de CSV), crie o
arquivo `.streamlit/secrets.toml` na raiz do projeto com o mesmo conteúdo
acima — esse arquivo já está no `.gitignore`, então não vai parar no GitHub
por engano.

---

## Como rodar na sua máquina

```bash
pip install -r requirements.txt
streamlit run app.py
```

Abre sozinho em `http://localhost:8501`.

---

## Como publicar de graça (Streamlit Community Cloud)

1. Crie uma conta no GitHub e um repositório **público** com estes arquivos.
2. Acesse `share.streamlit.io` e entre com o GitHub.
3. Clique em **New app**, escolha o repositório, branch `main`, arquivo `app.py`.
4. Em poucos minutos você recebe um link do tipo
   `https://seu-app.streamlit.app` — é esse link que vai no TCC.

**Atenção à persistência:** no Streamlit Cloud o disco é temporário. O histórico
em `dados/` some quando o servidor reinicia (algumas horas de inatividade). Para
a apresentação isso não atrapalha, porque o usuário envia os arquivos na hora.
Se quiser histórico permanente na nuvem, a alternativa mais simples é trocar as
funções `carregar_historico` / `salvar_historico` em `motor.py` por leitura e
escrita numa planilha do Google Sheets via `st.connection("gsheets")`. Rodando
localmente, o histórico em CSV persiste normalmente.

---

## Quais relatórios o usuário precisa baixar

No Portal do Parceiro, em **Análise**:

| Relatório | Aba usada | Colunas usadas |
|---|---|---|
| Cardápio | `Itens` | `Período`, `Nome do item`, `Vendas total (quantidade)` |
| Vendas | `Dias com mais vendas` | `Período`, `Dias`, `Total de Vendas (pedidos)` |

A leitura das colunas é por trecho do nome, sem acento e sem caixa
(`achar_coluna` em `motor.py`), então pequenas mudanças de cabeçalho do iFood
não quebram a ferramenta.

---

## O método de previsão

### Passo 1 — Dias de operação

O período vem como texto (`12/06/2026 - 12/08/2026`). A ferramenta conta quantas
vezes cada dia da semana ocorre dentro dele. Dias sem nenhum pedido são tratados
como **fechados** e retirados da conta.

Isso importa: no relatório de exemplo o período tem 62 dias corridos, mas a loja
não abre domingo. Dividir por 62 subestimaria a média diária em cerca de 15%.
A conta correta usa **53 dias de operação**.

### Passo 2 — Índice de sazonalidade de cada dia

```
índice(dia) = (pedidos do dia ÷ ocorrências do dia) ÷ (total de pedidos ÷ dias operados)
```

A divisão pelas ocorrências é o detalhe que costuma passar batido: num período de
dois meses pode haver 9 quartas e apenas 8 quintas. Sem esse ajuste, a quinta
apareceria com venda menor do que realmente tem.

Resultado no relatório de exemplo:

| Dia | Pedidos | Ocorrências | Média/dia | Índice |
|---|---|---|---|---|
| Segunda | 145 | 9 | 16,1 | 0,894 |
| Terça | 170 | 9 | 18,9 | 1,048 |
| Quarta | 216 | 9 | 24,0 | **1,332** |
| Quinta | 156 | 8 | 19,5 | 1,082 |
| Sexta | 177 | 9 | 19,7 | 1,091 |
| Sábado | 91 | 9 | 10,1 | **0,561** |

Leitura: quarta vende 33% acima de um dia médio; sábado, 44% abaixo.

### Passo 3 — Previsão por item

```
média diária(item)   = quantidade vendida no período ÷ dias operados
previsão(item, dia)  = média diária(item) × índice(dia) × (1 + margem de segurança)
```

Exemplo com a Coxinha Cremosa com Bacon (241 unidades no período):

```
241 ÷ 53 = 4,55 unidades/dia
quarta:  4,55 × 1,332 = 6,1 unidades
sábado:  4,55 × 0,561 = 2,6 unidades
semana:  27,3 unidades
```

### Margem de segurança

O slider na barra lateral aplica um acréscimo percentual sobre toda a previsão.
Ele existe porque o custo de faltar (venda perdida + cliente insatisfeito) quase
nunca é igual ao custo de sobrar. Em salgados, sobrar é barato; faltar na quarta
à noite, não. É uma decisão do gestor, não do modelo — por isso fica exposta na
interface.

---

## Validação

A aba **Validação** faz um backtest: usa o período anterior para prever o mais
recente e calcula o **MAPE** (erro percentual absoluto médio) por item.

Ela só funciona a partir do segundo envio, já que precisa de dois períodos para
comparar. Duas métricas são reportadas: o MAPE geral e o MAPE dos 10 itens mais
vendidos. O segundo costuma ser bem menor, e é o número que importa — um item
que vende 1 unidade por semana pode ter erro de 100% sem nenhum impacto na
produção, mas puxa a média geral para cima.

Para o TCC, vale reportar os dois e explicar a diferença.

---

## Limitações (vale declarar no trabalho)

- O relatório do iFood traz **pedidos** por dia da semana e **quantidade** por
  item no período agregado, sem cruzar os dois. A previsão assume que o mix de
  itens é o mesmo em todos os dias. É uma simplificação: se o cliente de sábado
  pede coisas diferentes do de quarta, o modelo não captura isso.
- O índice de sazonalidade é calculado sobre pedidos, não sobre itens. Se o
  tamanho médio do pedido variar por dia, há um viés pequeno.
- O método é uma média histórica ajustada por sazonalidade. Ele não prevê
  feriados, promoções, campanhas do iFood nem clima.
- A previsão cobre apenas vendas do iFood. Se a loja vende também no balcão ou
  no WhatsApp, o plano de produção precisa ser somado a essas fontes.

## Possível evolução

Comparar o método atual com Holt-Winters (`statsmodels`) usando o mesmo MAPE.
Com poucos períodos o modelo mais simples costuma ganhar, e mostrar isso com
número é um bom fechamento para o trabalho.
