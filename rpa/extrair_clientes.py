"""
RPA: extrai a lista de clientes da pagina web e envia para o Webhook do n8n.

Faz o que uma pessoa faria a mao: abre a pagina, le a tabela, e entrega os dados
ao sistema seguinte. Por isso e RPA e nao integracao: nao existe API do lado da
pagina, so HTML.

Uso:
    python extrair_clientes.py --dry-run      # extrai e mostra, nao envia
    python extrair_clientes.py                # extrai e envia ao n8n
    python extrair_clientes.py --com-ia       # pede mensagens geradas por LLM

Configuracao por variaveis de ambiente (nunca no codigo):
    N8N_WEBHOOK_URL   URL do webhook de producao
    RPA_TOKEN         token do header X-RPA-Token, exigido pelo webhook
"""

import argparse
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

URL_PAGINA = "https://digitalinnovationone.github.io/dio-lab-assistente-investimentos-rpa-n8n/"
WEBHOOK = os.environ.get("N8N_WEBHOOK_URL", "https://SEU_N8N/webhook/dio-investimentos")
TOKEN = os.environ.get("RPA_TOKEN", "")

TENTATIVAS = 3
ESPERA_BASE = 2  # segundos, dobra a cada tentativa


def saldo_para_numero(texto: str) -> float:
    """Converte 'R$ 12.500,00' em 12500.0.

    Em formato pt-BR o ponto e separador de milhar e a virgula e decimal, o
    contrario do que float() espera. Sem esta conversao explicita, 'R$ 850,00'
    seria lido como 85000.0 e 'R$ 12.500,00' como 12.5 -- erros de 1000x nos
    dois sentidos, que estragam a comparacao com o investimento minimo.
    """
    limpo = re.sub(r"[^\d,.]", "", texto)
    limpo = limpo.replace(".", "").replace(",", ".")
    return float(limpo)


def extrair_clientes() -> list[dict]:
    """Le a tabela #clientes da pagina e devolve uma lista de dicionarios."""
    resposta = requests.get(URL_PAGINA, timeout=30)
    resposta.raise_for_status()

    soup = BeautifulSoup(resposta.text, "html.parser")
    linhas = soup.select("#clientes tbody tr")
    if not linhas:
        raise RuntimeError(
            "Nenhuma linha encontrada em '#clientes tbody tr'. "
            "A estrutura da pagina mudou?"
        )

    clientes = []
    for linha in linhas:
        colunas = linha.find_all("td")
        if len(colunas) < 4:
            print(f"  aviso: linha ignorada, tem {len(colunas)} colunas", file=sys.stderr)
            continue

        saldo_texto = colunas[2].get_text(strip=True)
        clientes.append({
            "nome": colunas[0].get_text(strip=True),
            "email": colunas[1].get_text(strip=True),
            "saldo_texto": saldo_texto,
            "saldo": saldo_para_numero(saldo_texto),
            "perfil": colunas[3].get_text(strip=True),
        })

    return clientes


def enviar(clientes: list[dict], usar_ia: bool) -> dict:
    """Envia os clientes ao webhook, com repeticao em caso de falha de rede."""
    if not TOKEN:
        raise SystemExit(
            "RPA_TOKEN nao definido. Exporta o token antes de correr:\n"
            "    export RPA_TOKEN='...'    (bash/zsh)\n"
            "    set -x RPA_TOKEN '...'    (fish)"
        )

    corpo = {"clientes": clientes, "usar_ia": usar_ia}
    cabecalhos = {"X-RPA-Token": TOKEN, "Content-Type": "application/json"}

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = requests.post(WEBHOOK, json=corpo, headers=cabecalhos, timeout=300)
            if r.status_code == 403:
                raise SystemExit("403 do webhook: o RPA_TOKEN nao corresponde ao configurado no n8n.")
            r.raise_for_status()
            return r.json() if r.text.strip().startswith(("{", "[")) else {"resposta_crua": r.text}
        except (requests.Timeout, requests.ConnectionError) as erro:
            if tentativa == TENTATIVAS:
                raise
            espera = ESPERA_BASE ** tentativa
            print(f"  {type(erro).__name__} na tentativa {tentativa}/{TENTATIVAS}, "
                  f"nova tentativa em {espera}s", file=sys.stderr)
            time.sleep(espera)

    raise RuntimeError("inalcancavel")


def main() -> None:
    ap = argparse.ArgumentParser(description="RPA de extracao de clientes para o n8n")
    ap.add_argument("--dry-run", action="store_true", help="extrai e mostra, sem enviar")
    ap.add_argument("--com-ia", action="store_true", help="pede ao n8n mensagens geradas por LLM")
    args = ap.parse_args()

    print(f"A abrir {URL_PAGINA}")
    clientes = extrair_clientes()
    print(f"{len(clientes)} clientes extraidos:\n")
    for c in clientes:
        print(f"  {c['nome']:<18} {c['perfil']:<12} {c['saldo_texto']:>13}  ->  {c['saldo']:>10.2f}")

    if args.dry_run:
        print("\n--dry-run: nada enviado. Corpo que seria enviado:\n")
        print(json.dumps({"clientes": clientes, "usar_ia": args.com_ia},
                         ensure_ascii=False, indent=2)[:600] + "\n  ...")
        return

    print(f"\nA enviar para {WEBHOOK} (usar_ia={args.com_ia})")
    resultado = enviar(clientes, args.com_ia)

    mensagens = resultado if isinstance(resultado, list) else resultado.get("mensagens", resultado)
    print(f"\nResposta do n8n:\n")
    if isinstance(mensagens, list):
        for m in mensagens:
            print(f"--- {m.get('nome', '?')} ({m.get('perfil', '?')}) "
                  f"-> {m.get('produto_recomendado', '?')}")
            print(f"{m.get('mensagem', '')}\n")
        print(f"{len(mensagens)} mensagens recebidas.")
    else:
        print(json.dumps(mensagens, ensure_ascii=False, indent=2)[:1500])


if __name__ == "__main__":
    main()
