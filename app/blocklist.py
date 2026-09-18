"""A blocklist EXTRA do serviço: formas que o modelo marca e que não são nome (serviço 1.7).

O pacote do modelo já traz uma blocklist dentro do `manifest.json` — a do job que redige a
mesma coluna no servidor, congelada no momento do export. Só que ela **só age com
`ANONY_FILTROS=1`**, e esse modo liga junto dois outros filtros: o corte de confiança e a
exigência de maiúscula no span. O segundo custa recall (nome escrito todo em minúscula
deixa de ser redigido), e por isso o default do serviço sempre foi `0`: redigir TUDO que o
modelo marca.

Este módulo separa as duas coisas. `app/blocklist.txt` é uma lista **versionada neste
repositório** de formas medidas como não-nome — rótulo de campo de formulário, escala
clínica, fármaco, material, parentesco, cortesia —, e `ANONY_FILTROS=blocklist` aplica
**só ela** (unida à do manifesto), sem corte de confiança e sem exigência de maiúscula.
Redige menos exatamente onde a medição diz que não havia nome, e continua redigindo todo
o resto.

Não importa o runtime nem bs4, de propósito: é o que permite o CI conferir a lista e o
filtro antes do build de 200 MB (`python3 app/test_blocklist.py`).

**O que pode e o que não pode estar no arquivo.** Este repositório é público. Entra forma de
não-nome medida em produção; **não entra** nada com leitura de nome de pessoa real, nem nome
de hospital, cidade ou paciente — isso fica na lista do job, no servidor. A comparação é
por forma INTEIRA do span, em `casefold`, nunca por substring: `higiene` na lista não toca
em `Higienópolis`.
"""
import os

CAMINHO_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocklist.txt")


def carrega(caminho=CAMINHO_PADRAO):
    """Conjunto de formas em `casefold`. Linha vazia e `#` são ignorados."""
    formas = set()
    if not os.path.exists(caminho):
        return formas
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            t = linha.split("#", 1)[0].strip()
            if t:
                formas.add(t.casefold())
    return formas


def e_bloqueado(texto, blocklist):
    """A forma INTEIRA do span, em `casefold`, está na lista?"""
    return texto.strip().casefold() in blocklist


def filtra(spans, blocklist):
    """Devolve os spans cuja forma NÃO está na lista. `spans` são dicts com `texto`."""
    return [s for s in spans if not e_bloqueado(s["texto"], blocklist)]
