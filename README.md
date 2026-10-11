# Assistente de Investimentos com RPA e IA — minha solução

Resolução do desafio da DIO. O enunciado original está [mais abaixo](#criando-um-assistente-de-investimentos-com-rpa-e-ia-generativa), sem alterações.

## O que está entregue

| Entregável | Onde |
| --- | --- |
| Workflow do n8n | [`n8n/workflow.json`](n8n/workflow.json) |
| RPA ligado ao webhook | [`rpa/extrair_clientes.py`](rpa/extrair_clientes.py) e o notebook original |
| Mensagens estáticas (MVP) | ramo `Finalizar (template)` do workflow |
| Mensagens por LLM | ramo do agente, com dois modelos ligados |
| Envio por email, com validação | `Validar formato e domínio` → `Email válido?` → Gmail |
| Alerta de erro no Telegram | `Agrupar erros` → `Alertar erro no Telegram` |
| Decisões técnicas | [`DECISOES.md`](DECISOES.md) |

## Como corre

```
página HTML  ──scraping──>  RPA (Python)  ──POST──>  Webhook do n8n
                                                         │
                                       data.csv <──HTTP──┤
                                                         │
                                      cruzar perfil + filtrar por saldo
                                                         │
                                   validar email: formato, MX, autorização
                                                         │
                                        ┌────────────────┴───────────┐
                                     válido                      inválido
                                        │                            │
                           ┌────────────┴────────────┐               │
                      usar_ia = true          usar_ia = false        │
                           │                        │                │
                 agente (2 modelos)         template por perfil      │
                           └────────────┬───────────┘                │
                                        └──────────┬─────────────────┘
                                              resposta ao RPA
                                                   │
                                        ┌──────────┴──────────┐
                                     válido               inválido
                                        │                     │
                                 enviar Gmail        1 alerta no Telegram
```

Os vinte e três nós, pela ordem de execução:

1. `Webhook: clientes do RPA` — POST autenticado por header, responde pelo nó final
2. `Normalizar clientes` — valida o corpo, converte o saldo para número e fixa o modo
3. `Buscar investimentos (CSV)` — descarrega o `data.csv` **uma vez**
4. `Cruzar e recomendar` — cruza por perfil e filtra pelo saldo mínimo
5. `Validar formato e domínio` → `Verificar MX do domínio` → `Consolidar validação`
6. `Email válido?` — os inválidos saem do fluxo antes de gastarem uma chamada ao modelo
7. `Mensagem por template` — gera o texto estático para todos os clientes válidos
8. `Usar IA?` — desvia conforme o campo `usar_ia` do pedido
9. `Dividir em lotes` + `Aguardar (limite de taxa)` — uma chamada ao modelo por vez
10. `Gerar mensagem com IA` — agente com modelo principal e modelo de reserva
11. `Finalizar (IA)` / `Finalizar (template)` — normalizam a saída e marcam a origem
12. `Juntar resultados` — junta válidos e inválidos para a resposta ser completa
13. `Responder ao RPA` — devolve o estado de cada cliente ao script
14. `Rotear entrega` — depois da resposta, separa envios de alertas
15. `Enviar email (Gmail)` — destinatário conforme o modo
16. `Agrupar erros` → `Alertar erro no Telegram` — um alerta com todas as falhas

## Modo demo e modo produção

O corpo do pedido traz um campo `modo`:

| Modo | Destinatário do email | Domínios de exemplo |
| --- | --- | --- |
| `demo` (por omissão) | o endereço do operador, com `[demo]` no assunto | aceites |
| `producao` | o endereço real do cliente | bloqueados, com alerta no Telegram |

O email do cliente **nunca é alterado** nos dados. O que muda é para onde o envio vai, e
isso decide-se no fim, no campo `destinatario_efetivo`.

Omitir o campo, ou enviá-lo com um valor desconhecido, resulta em `demo`. Um fluxo que
envia correio para fora deve falhar para o lado seguro.

## Como executar

Importar `n8n/workflow.json` no n8n e criar quatro credenciais na instância: uma
*Header Auth* com o cabeçalho `X-RPA-Token` e um token à escolha, uma do modelo de
linguagem, uma do Gmail e uma do Telegram.

No ficheiro publicado, dois valores estão como marcadores e têm de ser substituídos:
`SEU_CHAT_ID_TELEGRAM` no nó do Telegram, e `operador@exemplo.com` como destinatário por
omissão do modo demo (que a variável `EMAIL_DEMO` também sobrepõe). São identificadores do
operador e não têm de viver num repositório público. Depois, na máquina que corre o RPA:

```bash
pip install requests beautifulsoup4

export N8N_WEBHOOK_URL="https://SEU_N8N/webhook/dio-investimentos"
export RPA_TOKEN="o-mesmo-token-da-credencial"
export EMAIL_DEMO="o-teu@email.com"   # destinatário de tudo em modo demo

python rpa/extrair_clientes.py --dry-run   # extrai e mostra, não envia
python rpa/extrair_clientes.py             # MVP: template, emails em modo demo
python rpa/extrair_clientes.py --com-ia    # mensagens geradas pelo modelo
python rpa/extrair_clientes.py --producao  # envia para o endereço real do cliente
```

O token não está neste repositório de propósito: o webhook fica exposto na internet e
quem souber o URL poderia injetar clientes inventados no fluxo.

## Resultado

As dez recomendações, com os três casos em que o filtro por saldo muda a resposta:

| Cliente | Perfil | Saldo | Recomendado | Excluído por saldo |
| --- | --- | --- | --- | --- |
| Ana Silva | Conservador | R$ 12.500,00 | CDB Liquidez Diária | — |
| Bruno Lima | Moderado | R$ 3.200,00 | CDB Prefixado | Fundo Multimercado |
| Carla Souza | Arrojado | R$ 28.900,00 | Fundo de Ações | — |
| Daniel Oliveira | Conservador | R$ 850,00 | Tesouro Selic | CDB Liquidez Diária |
| Elena Rodrigues | Arrojado | R$ 45.000,00 | Fundo de Ações | — |
| Felipe Santos | Moderado | R$ 7.800,00 | Fundo Multimercado | — |
| Gabriela Costa | Conservador | R$ 1.500,00 | CDB Liquidez Diária | — |
| Henrique Alves | Moderado | R$ 22.300,00 | Fundo Multimercado | — |
| Isabela Martins | Conservador | R$ 500,00 | Tesouro Selic | CDB Liquidez Diária |
| João Pereira | Arrojado | R$ 15.000,00 | Fundo de Ações | — |

Por que isto importa, e as outras decisões do caminho: [`DECISOES.md`](DECISOES.md).

---

# Criando um Assistente de Investimentos com RPA e IA Generativa

## Descrição

Aprenda na prática como criar um fluxo de automação inteligente combinando técnicas de RPA (Robotic Process Automation) com workflows de IA no N8N.

Neste desafio, você vai construir um assistente de investimentos automatizado. O fluxo começa com a extração de dados de clientes em uma página web usando Python, passa pela orquestração de um workflow no N8N e termina com a geração de mensagens personalizadas para cada perfil de investidor.

O projeto foi pensado para ser simples e acessível, mesmo para quem está dando os primeiros passos em Python e automação. A ideia é que você entenda o conceito de RPA de forma leve e aplique tudo em um cenário realista do mercado financeiro.

## Objetivo do Projeto

Desenvolver um pipeline de automação que:

1. **Coleta dados de clientes** de uma página web simulada usando Python
2. **Processa as informações** através de um workflow no N8N
3. **Cruza perfis de investidor** com uma base de opções de investimento
4. **Gera mensagens personalizadas** para cada cliente

Ao final, você terá um sistema funcional que demonstra como empresas do setor financeiro podem automatizar a comunicação com clientes de forma inteligente.

## Arquitetura do Projeto

```mermaid
flowchart LR
  %% Pipeline RPA + N8N + IA (máx. 7 caixinhas)

  subgraph GH["GitHub Pages"]
    A["Clientes<br>(docs/index.html)"]
    E["Investimentos (docs/data.csv)"]
  end

  subgraph PY["RPA (Python)"]
    B["Extrair Clientes"]
  end

  subgraph N8["N8N (Workflow)"]
    C["Webhook<br>(Entrada)"]
    D["Cruzar Dados<br>(Clientes x Investimentos)"]
    M["Gerar Mensagem<br>(Template/LLM)"]
    C --> D --> M
  end

  subgraph OUT["Saída"]
    O["Mensagens Personalizadas"]
  end

  A <-->|HTTP| B --> C
  E <-->|HTTP| D
  M --> O

  %% Estilos
  classDef source fill:#E3F2FD,stroke:#1E88E5,stroke-width:1px,color:#0D47A1;
  classDef rpa fill:#E8F5E9,stroke:#43A047,stroke-width:1px,color:#1B5E20;
  classDef n8n fill:#FFF3E0,stroke:#FB8C00,stroke-width:1px,color:#E65100;
  classDef out fill:#FCE4EC,stroke:#D81B60,stroke-width:1px,color:#880E4F;

  class A,E source;
  class B rpa;
  class C,D,M n8n;
  class O out;

```

## Tecnologias e Ferramentas

O projeto utiliza ferramentas gratuitas e acessíveis, organizadas conforme cada etapa do fluxo:

| Etapa | Ferramenta | Função |
|-------|-----------|--------|
| Hospedagem | GitHub Pages | Servir a página de clientes e o CSV de investimentos |
| Extração (RPA) | Python + BeautifulSoup | Coletar dados dos clientes via web scraping |
| Orquestração | N8N | Processar dados, cruzar perfis e gerar mensagens |
| Geração com IA | Agente de IA no N8N | Criar mensagens personalizadas com LLM (desafio extra) |

Além dessas, você pode usar IAs generativas como **Gemini**, **Claude** ou **ChatGPT** como copilotos para auxiliar na escrita de código e tirar dúvidas ao longo do desenvolvimento.

## Roteiro do Desafio

### Etapa 1: Entenda o Projeto

Antes de começar, explore o repositório base que já contém a estrutura inicial:

1. **Página de Clientes (`docs/index.html`):** Uma página HTML hospedada no GitHub Pages com uma lista de clientes fictícios contendo nome, email, saldo e perfil de investidor (Conservador, Moderado ou Arrojado). Disponível online [neste link](https://digitalinnovationone.github.io/dio-lab-assistente-investimentos-rpa-n8n).
2. **Dados de Investimentos (`docs/data.csv`):** Um arquivo CSV também hospedado no GitHub Pages com opções de investimento organizadas por perfil. Disponível online [neste link](https://digitalinnovationone.github.io/dio-lab-assistente-investimentos-rpa-n8n/data.csv).
3. **Script de RPA (`src/extrair_clientes.ipynb`):** Um notebook Python que acessa a página de clientes e extrai os dados da tabela usando BeautifulSoup.

> 🤖 **Por que o script é considerado RPA?** Ele faz exatamente o que um humano faria manualmente: abre uma página, lê os dados de uma tabela e os envia para outro sistema. A diferença é que o "robô" (código) executa isso automaticamente. Essa abordagem é útil quando não existe uma API disponível ou quando precisamos integrar sistemas legados.

### Etapa 2: Configure o Ambiente

1. Faça um **fork** do repositório base para sua conta do GitHub
2. Crie uma conta no [N8N Cloud](https://n8n.io/) ou instale localmente
3. Abra o notebook `src/extrair_clientes.ipynb` no [Google Colab](https://colab.research.google.com/) e execute para entender o fluxo de extração

> 💡 **Atenção:** O script já extrai os dados, mas o envio ao N8N está comentado (`TODO`). Você vai configurar a URL do Webhook após criá-lo na próxima etapa.

### Etapa 3: Desenvolva o Workflow no N8N

Este é o coração do desafio! Monte um fluxo que:

1. Receba os dados dos clientes via Webhook (copie a URL gerada e configure no script Python)
2. Leia o arquivo `docs/data.csv` com as opções de investimento
3. Cruze o perfil de cada cliente com a opção adequada
4. Gere uma mensagem de recomendação para cada cliente

### Etapa 4 (MVP): Mensagens Estáticas

Para a versão mínima, use templates de mensagem fixos baseados no perfil:

- **Conservador:** Foco em renda fixa e segurança
- **Moderado:** Mix equilibrado entre renda fixa e variável
- **Arrojado:** Ênfase em ações e maior potencial de retorno

### Etapa 5 (Desafio): Integração com IA Generativa

Conecte o Agente de IA do N8N a um modelo como Gemini ou GPT para:

- Analisar o contexto do cliente (saldo, perfil)
- Gerar mensagens únicas e personalizadas
- Criar recomendações mais inteligentes e humanizadas

## Entregáveis

### MVP (Mínimo Viável)

- [ ] Repositório forkado com o workflow N8N implementado
- [ ] Workflow N8N exportado (`n8n/workflow.json`) com mensagens estáticas
- [ ] Script de RPA integrado ao Webhook do N8N
- [ ] Print ou vídeo demonstrando o fluxo funcionando de ponta a ponta

### Desafio Completo

- [ ] Todos os itens do MVP
- [ ] Integração com Agente de IA no N8N
- [ ] Mensagens geradas dinamicamente via LLM
- [ ] Documentação explicando as decisões técnicas

## Estrutura do Repositório

```
📁 dio-lab-assistente-investimentos-rpa-n8n/
├── 📄 README.md
├── 📁 src/
│   └── 📄 extrair_clientes.ipynb   # ✅ Notebook Python (já implementado, falta só o TODO)
├── 📁 n8n/
│   └── 📄 workflow.json            # 🎯 Seu desafio: exportar o workflow aqui
└── 📁 docs/
    ├── 📄 index.html               # ✅ Página de clientes (já implementado)
    └── 📄 data.csv                 # ✅ Opções de investimento (já implementado)
```

## Prompts Úteis para Copilotos de IA

| Tarefa | Sugestão de Prompt |
|--------|-------------------|
| Gerar dados fictícios | "Crie 10 clientes fictícios com nome, email, saldo e perfil de investidor em JSON" |
| Entender código | "Explique o que faz a biblioteca BeautifulSoup em Python" |
| Debugar erros | "Meu script Python está dando erro X, o que pode ser?" |
| Montar workflow | "Como configuro um webhook no N8N para receber dados JSON?" |

## Referências

- [Documentação do N8N](https://docs.n8n.io/)
- [BeautifulSoup: Web Scraping com Python](https://realpython.com/beautiful-soup-web-scraper-python/)
- [GitHub Pages: Guia Rápido](https://pages.github.com/)

---

**Bons estudos e mãos à obra** 🚀

Se tiver dúvidas, lembre-se: a melhor forma de aprender é experimentando. Erre, corrija e celebre cada pequena vitória no caminho.
