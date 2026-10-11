# Decisões técnicas

Notas sobre o que decidi enquanto montava o fluxo, e porquê. A ordem é mais ou
menos a ordem em que os problemas apareceram.

## 1. O cruzamento por perfil, só por si, dá recomendações impossíveis

O enunciado pede para "cruzar o perfil de cada cliente com a opção adequada". Mas o
`data.csv` tem uma coluna `minimo` e os clientes têm saldo, e os números não encaixam
todos. Cruzando apenas por perfil, três dos dez clientes recebem uma recomendação que
não conseguem seguir:

| Cliente | Perfil | Saldo | Produto que não alcança |
| --- | --- | --- | --- |
| Isabela Martins | Conservador | R$ 500,00 | CDB Liquidez Diária (mínimo R$ 1.000) |
| Daniel Oliveira | Conservador | R$ 850,00 | CDB Liquidez Diária (mínimo R$ 1.000) |
| Bruno Lima | Moderado | R$ 3.200,00 | Fundo Multimercado (mínimo R$ 5.000) |

Por isso o nó `Cruzar e recomendar` filtra por `saldo >= minimo` antes de escolher. Os
produtos descartados por saldo não desaparecem: ficam no campo `excluidos_por_saldo`,
porque é informação útil para quem analisa o fluxo, mas nunca entram na mensagem que o
cliente recebe.

## 2. O saldo chega como texto e o formato é brasileiro

A página serve `R$ 12.500,00`. Em pt-BR o ponto é separador de milhar e a vírgula é
decimal, ao contrário do que `float()` e `Number()` esperam. Um parse ingénuo erra por
um fator de mil, nos dois sentidos:

```
"R$ 12.500,00"  ->  12.500,00     parse ingénuo:     12,50
"R$ 850,00"     ->     850,00     parse ingénuo: 85.000,00
"R$ 500,00"     ->     500,00     parse ingénuo: 50.000,00
```

Isto não é cosmético: com o parse errado a Isabela passa a "ter" R$ 50.000 e o filtro do
ponto 1 deixa de proteger ninguém. A conversão é explícita em dois sítios — no RPA, para
quem lê o JSON enviado, e outra vez no nó `Normalizar clientes`, porque o webhook é uma
porta aberta e não deve confiar que o cliente do outro lado fez a conversão.

## 3. Escolher entre os produtos acessíveis

Depois do filtro, sobram vários produtos por cliente. A regra que usei: **o de maior
mínimo entre os que o saldo alcança**, com desempate alfabético. É o produto mais exigente
que o cliente consegue contratar, e os restantes seguem na mensagem como alternativas.

Pensei em ordenar por rentabilidade, que seria o mais óbvio, e desisti: a coluna não é
comparável. Tem `12.5%`, `IPCA+6.0%` e `Variável` na mesma coluna. Ordenar aquilo exigia
inventar uma equivalência entre taxa pré-fixada, taxa indexada à inflação e renda
variável, que é uma decisão financeira e não de código. O mínimo é um número e está lá.

## 4. Buscar o CSV uma vez, não dez

No n8n, um nó corre uma vez por item que recebe. Se os clientes forem separados em dez
itens antes do pedido HTTP, o CSV é descarregado dez vezes para dar sempre o mesmo
resultado. Por isso o `Normalizar clientes` devolve **um único item** com a lista toda
dentro, o CSV é buscado nesse estado, e a separação em dez itens só acontece no
`Cruzar e recomendar`, que lê os clientes com `$('Normalizar clientes')`.

## 5. A mensagem por template é calculada sempre, mesmo quando se usa IA

O nó `Mensagem por template` corre antes do desvio para a IA e deixa o texto estático em
`mensagem_template` para todos os clientes. Parece desperdício e é o contrário: é o que
permite ter um fallback a sério. Quando o LLM não responde, o nó `Finalizar (IA)` usa o
template e marca o campo `origem` como `template (fallback: a IA não respondeu)`, em vez
de devolver uma mensagem vazia ou rebentar a execução.

Foi esta decisão que salvou a primeira corrida com IA: o nome do modelo estava errado, as
dez chamadas falharam, e a execução ainda assim terminou com `success` e dez mensagens
entregues. O campo `origem` disse-me exatamente o que tinha acontecido.

## 6. Dois modelos, e o Gemini não é o principal

O enunciado sugere Gemini. Comecei por aí e esbarrei em duas coisas:

- `models/gemini-2.0-flash` e `models/gemini-1.5-flash` devolvem *resource not found*.
  O que responde é `models/gemini-2.5-flash`.
- Mesmo com o nome certo, o free tier recusa com *too many requests* a partir da quarta
  ou quinta chamada seguida. A quota é por minuto e está partilhada com os outros
  workflows da mesma instância, portanto não depende só deste fluxo.

Em vez de aceitar um resultado que varia a cada corrida, o nó do agente tem dois modelos
ligados: um modelo gratuito via OpenRouter como principal, e o Gemini como reserva na
entrada de fallback. Provedores diferentes, quotas diferentes: a recusa de um não manda a
mensagem para o template.

Além disso, as chamadas passam por um `Loop Over Items` com uma espera entre clientes.
Dispará-las todas de uma vez fazia metade falhar por limite de taxa. A espera começou em
5 segundos e teve de descer para 2 pela razão do ponto 7.

Os dois nós de modelo têm `timeout` e `maxRetries: 0`. Sem isso, um modelo gratuito que
simplesmente não responde — e aconteceu-me com um — deixa a execução pendurada em
`running` para sempre, em vez de falhar e deixar a reserva entrar. Um provedor mudo é um
caso mais chato do que um provedor que recusa: a recusa é imediata e tratável, o silêncio
não. Falhar depressa é um requisito, não uma otimização.

## 7. O túnel corta a resposta aos 100 segundos

A instância do n8n é servida por um túnel da Cloudflare, e a Cloudflare fecha a ligação se
a origem demorar mais de cerca de 100 segundos a responder. Com dez clientes e 5 segundos
de espera entre chamadas ao modelo, a execução passava dos 110 segundos: o workflow
terminava bem do lado do n8n, mas o RPA recebia um erro `524` e nunca via as mensagens.

Baixei a espera para 2 segundos, o que põe a corrida completa por volta dos 50 a 60
segundos, com margem. A alternativa mais correta para uso real seria outra arquitetura: o
webhook responder de imediato com um "recebido" e o resultado ser entregue por outro
caminho, em vez de manter o pedido HTTP aberto durante a geração das dez mensagens. Para
este desafio, em que o enunciado quer ver as mensagens a voltar ao script, a resposta
síncrona é o que faz sentido — mas é uma decisão com um tecto conhecido, e o tecto é este.

## 8. O webhook está autenticado porque a instância está na internet

O n8n desta montagem está exposto por um túnel, com URL público. Um webhook sem
autenticação significa que qualquer pessoa que descubra o endereço pode injetar clientes
inventados no fluxo. O nó do webhook está atrás de *Header Auth*, com um token em
`X-RPA-Token`.

O token vive em dois sítios: numa credencial do n8n e numa variável de ambiente na máquina
que corre o RPA. Não está neste repositório, que é público, e é por isso que o script lê
`RPA_TOKEN` do ambiente em vez de o ter no código.

## 9. Um só workflow para o MVP e para o desafio completo

O corpo do pedido traz um campo `usar_ia`. Um nó `IF` desvia para o ramo da IA ou para o
ramo do template, e os dois voltam a juntar-se no `Responder ao RPA`. Dois ficheiros
separados, um para o MVP e outro para a versão com IA, iam divergir ao primeiro ajuste no
cruzamento — que é a parte que ambos partilham.

Do lado do RPA é a diferença entre `python extrair_clientes.py` e
`python extrair_clientes.py --com-ia`.

## Limitações que ficam conhecidas

- **O scraping depende da estrutura da página.** O seletor é `#clientes tbody tr` e as
  colunas são lidas por posição. Se a página mudar de forma, o script falha — de
  propósito, com erro explícito, em vez de enviar dados vazios.
- **Sem persistência.** O fluxo responde ao pedido e não guarda nada. Para uso real
  faltava gravar as mensagens com data, para não repetir a mesma recomendação na semana
  seguinte.
- **O free tier continua a poder recusar.** Com dois provedores e espera entre chamadas
  é raro, mas quando acontece a mensagem sai pelo template, e o campo `origem` diz isso.
- **A IA pode reformular números.** O prompt proíbe inventar produtos e valores, e a
  mensagem só recebe o produto já escolhido pelo código — a decisão de investimento não é
  do LLM, é da regra do ponto 3. Mesmo assim, uma reformulação do tipo "16,0% ao ano"
  quando o CSV diz apenas `16.0%` é possível. É um dos sítios onde eu não deixaria isto
  ir para produção sem revisão humana.
