"""Teste do motor de calculo com os relatorios reais do iFood."""
import motor
U = "/mnt/user-data/uploads/"
c = U + "relatorio-cardápio_af60ab4f4da2f7f81a1a21ffde56ed8b231add12e44061e74ae0eaeeb627d85a.xlsx"
v = U + "relatorio_vendas_47e88094757aef17ef17cfe8e39544f070e678f56900a6ba0b8b9b5bcb7dc9e1.xlsx"

it = motor.ler_relatorio_cardapio(c)
di = motor.ler_relatorio_vendas(v)
print("itens:", it.shape, "| dias:", di.shape)
print(di.to_string(index=False))

saz, dop, tot = motor.calcular_sazonalidade(di)
print("\ndias operados:", dop, "| pedidos:", tot)
print(saz.round(3).to_string(index=False))

prev = motor.calcular_previsao(it, saz, dop, 0.10)
print("\n", prev.head(6).round(1).to_string(index=False))
print("\nsoma semanal do top item:", round(prev['Total da semana'].iloc[0],1))
print("validacao (1 periodo) vazia?", motor.validar_modelo(it, di).empty)
