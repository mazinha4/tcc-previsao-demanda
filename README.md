# Ferramenta de planejamento de produção a partir das vendas do iFood

Aplicação web que recebe os relatórios exportados do Portal do Parceiro iFood e
devolve **quanto produzir de cada item em cada dia da semana**.

O usuário final só vê a interface: envia dois arquivos `.xlsx` e recebe o plano
de produção. Todo o cálculo fica escondido em `motor.py`.

---

## Arquivos

| Arquivo | Função |
|---|---|
| `app.py` | Interface (Streamlit). Upload, abas, gráficos, download do plano. |
| `motor.py` | Lógica pura: leitura das planilhas, sazonalidade, previsão, validação. Não depende do Streamlit. |
| `teste.py` | Roda o motor pelo terminal com uma planilha de exemplo. Útil para a seção de resultados do TCC. |
| `requirements.txt` | Dependências. |
| `dados/` | Histórico acumulado (criado automaticamente). |

Separar `motor.py` da interface não é enfeite: permite testar o cálculo sem
abrir o navegador e deixa claro na defesa o que é ferramenta e o que é método.

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
