"""Como o span vira `***` no texto original.

Separado do `main.py` pela mesma razao do `orcamento.py`: nao importa fastapi, bs4, nltk
nem o runtime do pacote, entao o CI confere esta decisao em segundos, sem baixar os 200 MB
do modelo e sem CPU para inferencia. Rode com `python3 app/test_redacao.py`.

**O problema que este modulo existe para resolver: o modelo ACHA o nome e a redacao o
descarta, sem log.** Ate a versao 1.4 do servico a substituicao era

    re.sub(r"\\b(" + re.escape(span) + r")\\b", "***", texto, flags=re.IGNORECASE)

e ela falha calada em duas familias, as duas medidas em 170 evolucoes reais do `doamor`
(2026-09-12, pacote o1.3, as pendentes do dia):

- **espaco que nao e espaco.** O runtime remonta a forma do span juntando TOKENS com
  espaco comum; o texto do hospital tem `\\xa0` (NBSP) entre as palavras. `re.escape(" ")`
  e um espaco literal e nao casa `\\xa0`. **5 dos 28 spans de producao (17,9%) tinham essa
  divergencia**, e dois deles eram nome de paciente — um nome completo. 122 de 166 daqueles
  documentos tem NBSP em algum lugar;
- **`\\b` na borda que nao e palavra.** `\\b` exige transicao palavra/nao-palavra, entao
  span que COMECA ou TERMINA em pontuacao nunca casa: `Everton,` e `(  Rosangela` — formas reais
  do mesmo dia — passavam batido. O `\\b` so faz sentido na borda que e alfanumerica.

A mesma familia ja era conhecida pelo zero-width (`docs/anony-onnx-intranet.md`): o flair
remove `\\u200b` ANTES de tokenizar e funde as metades, entao o span sai `PacienteMaria`,
string que nao existe no texto — e a redacao por forma a descarta. Aqui o conserto e o
mesmo e sai de graca: tolerar o invisivel no padrao.

**O que NAO muda:** continua sendo redacao por FORMA, com `IGNORECASE`, em TODAS as
ocorrencias, sobre o texto original com HTML. Nome achado no prefixo lido segue sendo
apagado onde reaparece na cauda nao lida. O que muda e o conjunto de ocorrencias que a
forma alcanca — ele deixa de depender de qual espaco o hospital digitou.
"""
import re

# Invisiveis que o flair remove antes de tokenizar (`Sentence._handle_problem_characters`)
# e que por isso somem da forma do span, mas seguem no texto original. `​` e `‌`
# NAO sao whitespace em Unicode, entao `\s` nao os pega: precisam de classe propria.
INVISIVEIS = "​‌‍⁠﻿️"
_INV = f"[{INVISIVEIS}]*"
# Whitespace de verdade (`\s` ja cobre `\xa0`, ` `, ` `, `　` em padrao str)
# MAIS os invisiveis: `Maria​ Angelica` tem de casar a forma `Maria Angelica`.
_ESP = f"(?:\\s|[{INVISIVEIS}])+"


def _e_palavra(c):
    """O que `\\b` considera palavra em padrao str: alfanumerico Unicode ou `_`."""
    return c.isalnum() or c == "_"


def padrao_do_span(span):
    """Regex que casa a forma do span tolerando espaco exotico e invisivel.

    `None` para span sem nenhum alfanumerico: sem isso o padrao ficaria sem ancora e
    casaria posicao vazia pelo texto inteiro. Com `ANONY_FILTROS=0` o servico redige TUDO
    que o modelo marca, entao esse guard nao e hipotetico.
    """
    if not any(c.isalnum() for c in span):
        return None
    partes = []
    for pedaco in re.split(r"(\s+)", span):
        if not pedaco:
            continue
        if pedaco.isspace():
            partes.append(_ESP)
        else:
            partes.append(_INV.join(re.escape(c) for c in pedaco))
    corpo = _INV.join(partes)
    # `\b` SO onde a borda do span e alfanumerica. Em `Everton,` a borda direita e a virgula:
    # exigir `\b` depois dela e exigir uma transicao que quase nunca existe.
    ini = r"\b" if _e_palavra(span[0]) else ""
    fim = r"\b" if _e_palavra(span[-1]) else ""
    return ini + "(" + corpo + ")" + fim


def _casa(padrao, texto):
    return padrao is not None and re.search(padrao, texto, flags=re.IGNORECASE) is not None


def trechos_que_casam(span, texto):
    """Decompoe o span nos maiores trechos CONTIGUOS que existem de fato no texto.

    Duas coisas quebram a forma inteira, e as duas sao de LAYOUT, nao de modelo:

    - o modelo le o texto sem HTML e as vezes emite UM span por cima de uma fronteira de
      paragrafo — `Anexo Marlene Ferraz Tondo`, com `Anexo` num `<p>` e o nome no seguinte;
    - a tag pode cair DENTRO do nome — `Maria<b> </b>Angelica` —, e ai a forma nao casa
      inteira mas as duas metades existem.

    Guloso: acha o maior trecho que casa, e repete a esquerda e a direita dele. No primeiro
    caso devolve `["Marlene Ferraz Tondo"]` e o `Anexo` fica de fora se nao existir sozinho;
    no segundo devolve `["Maria", "Angelica"]` — as duas metades do nome, que e o ponto.
    Lista vazia = nada do span existe no texto, e ai nao ha o que redigir.
    """
    def rec(tokens):
        if not tokens:
            return []
        n = len(tokens)
        for tamanho in range(n, 0, -1):
            for i in range(0, n - tamanho + 1):
                trecho = " ".join(tokens[i:i + tamanho])
                if trecho == span:
                    continue          # a forma inteira ja foi tentada por quem chamou
                if _casa(padrao_do_span(trecho), texto):
                    return rec(tokens[:i]) + [trecho] + rec(tokens[i + tamanho:])
        return []
    return rec(span.split())


def redige(spans, texto, por_pedacos=True):
    """Troca cada span por `***` no texto, todas as ocorrencias, ignorando caixa.

    `por_pedacos` (env `ANONY_REDACAO_PEDACOS`, ligado por default) e o FALLBACK, e so
    dispara onde hoje nao acontece NADA: span cuja forma inteira nao casa em lugar nenhum.
    Ai redige os `trechos_que_casam`.

    Medido pelo `/clean` nas 170 pendentes do `doamor` de 2026-09-12, com o pacote o1.3 e o
    caminho do servico (mesma lista de spans dos dois lados, so a substituicao muda) — os
    numeros estao no relato da mudanca. O preco e redigir algum termo clinico que hoje
    escapa por acidente (`Queda`, cor de triagem), e a redacao e por forma, entao apaga
    todas as ocorrencias daquele termo na nota. E a mesma escolha que o produto ja fez em
    2026-08-30 ao publicar o `f1.5` ("nome perdido e vazamento, lixo e redacao a mais"), e
    por isso e um KNOB e nao uma regra: `ANONY_REDACAO_PEDACOS=0` volta a so redigir a forma
    inteira, que e o comportamento do servico 1.4.
    """
    resultado = texto
    for span in spans:
        padrao = padrao_do_span(span)
        if _casa(padrao, resultado):
            resultado = re.sub(padrao, "***", resultado, flags=re.IGNORECASE)
            continue
        if not por_pedacos:
            continue
        for trecho in trechos_que_casam(span, resultado):
            padrao = padrao_do_span(trecho)
            if padrao is not None:
                resultado = re.sub(padrao, "***", resultado, flags=re.IGNORECASE)
    return resultado
