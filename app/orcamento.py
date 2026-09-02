"""Orcamento de tempo do /clean: decide ANTES de processar se cabe na paciencia do cliente.

## O problema que isto resolve (medido em 2026-09-01, na frota)

O `InvokeHTTP` do NiFi que chama este servico declara **Read Timeout de 15 s** na
esmagadora maioria dos processadores (86 de 92 numa box; 15 s tambem no padrao das outras).
Quando o `/clean` demora mais que isso, tres coisas acontecem, nesta ordem:

1. o cliente desiste e o flowfile cai no Failure — que o flow auto-termina, entao a nota
   nao e escrita;
2. **este servico continua processando** um pedido que ninguem espera, queimando CPU;
3. o `Full Load` reprocessa a mesma nota, que de novo demora mais que 15 s, e de novo e
   descartada. O trabalho perdido nao e pontual: e um laco.

Em CPU moderna isso nao acontece (medido: 9,2 mil chars em 1,8 s; 76 mil em 13,0 s). Em
Xeon E5420 de 2007 acontece cedo: 5.952 chars em 9,7 s e **7.936 chars em 24,5 s**. E o
tamanho de nota varia duas ordens de grandeza entre clientes — p50 de 8 chars num, 1.652 em
outro, com 13% acima de 7 mil. Ou seja o mesmo texto e barato numa box e impossivel na
outra: **o corte nao pode ser uma constante de codigo**, tem de sair do que a maquina
consegue.

## Por que estimar, e nao interromper no meio

Interromper exigiria checkpoint dentro da inferencia, e no modo `documento` a chamada ao
runtime e uma so, de proposito — e o contexto de documento inteiro que compra os 31 pontos
de recall. Reparti-la para poder olhar o relogio desfaria justamente a mudanca que ela
existe para fazer. Entao a decisao e na porta: se a estimativa nao cabe, recusa em
milissegundos, sem comecar. O cliente recebe o mesmo desfecho que receberia (nota nao
escrita), so que **em 5 ms em vez de 25 s, e com o motivo dito em vez de um timeout mudo**.

## O que fazer quando nao cabe: `parcial` (default) ou `recusa`

Recusar entrega o desfecho certo para o PACIENTE (nada meio-redigido e gravado) e o errado
para o DADO: a nota nao existe. Onde o cliente nao consegue reprocessar — flow que
auto-termina o `Failure` e cursor que nao volta —, isso e perda definitiva de evolucao
clinica. Medido em 2026-09-02 numa box de hospital: 175 notas descartadas em 26 h, todas as
longas, sem fila para inspecionar.

O default e `parcial`: le o prefixo que cabe, redige esse prefixo e devolve o resto como
original, com **200** e com o quanto ficou por ler dito na resposta. `ANONY_ORCAMENTO=recusa`
volta ao 413 com nada processado, para quem prefere nao gravar nota meio redigida e
CONSEGUE reprocessar a recusada.

Ele e o default porque a alternativa real, na frota, nao e "nota inteira redigida": e nota
nenhuma. Sem orcamento o texto longo estoura o Read Timeout do cliente e o flow descarta o
flowfile sem registrar nada. O que o parcial troca, entao, e **perda silenciosa por redacao
parcial declarada** — e nao redacao completa por redacao parcial.

⚠️ Ha uma faixa em que a troca e no outro sentido: nota cuja inferencia levaria entre o
`ANONY_TIMEOUT_S` e o Read Timeout do cliente (13 s e 15 s nos defaults) hoje e escrita
INTEIRA redigida, e passa a sair parcial. A faixa e estreita e a estimativa erra para o lado
de cortar cedo, entao ela existe; quem nao a aceita poe `ANONY_ORCAMENTO=recusa` e volta ao
comportamento anterior — ou sobe os dois tetos juntos. Ele NAO e o modo `frase` de volta. Sao tres diferencas, e as tres importam:

1. **O corte e medido, nao constante.** `chars_que_cabem` e o inverso exato de
   `cabe_no_orcamento`, entao o prefixo lido e o maximo que a recusa teria aceitado naquela
   maquina — nao os ~2.000 chars fixos do `MAX_TIME`.
2. **O prefixo vai numa chamada so, com contexto de documento.** A objecao da secao acima e
   a reparticao DENTRO da inferencia; cortar o texto ANTES e outra coisa. Pelos numeros da
   avaliacao (comentario de `CONTEXTO` em `main.py`): dos 548 nomes que o modo `frase`
   deixa em claro, 519 estao em trecho nunca lido e so 29 sao erro de modelo. Ou seja o
   custo de recall e de nao ler, nao de fragmentar — e o parcial le o maximo possivel.
3. **O parcial e declarado.** A resposta ganha `redacao: "parcial"` e `chars_nao_lidos`. O
   200 mudo com texto meio-redigido continua nao existindo: e ele o mecanismo dos 519
   nomes, porque o cliente grava e nada no monitoramento acusa.

E ha um piso: se nem a primeira frase cabe, `parcial` **recusa** como o default. Um 200 com
o texto inteiro em claro nao e redacao parcial, e nenhum rotulo o torna aceitavel.

## O teto do orcamento, e onde ele deixa de segurar

O orcamento modela a INFERENCIA do prefixo. O pedido paga, alem dela, um custo que cresce
com o texto INTEIRO e que nenhum corte de prefixo evita: `replace_breaklines`,
`remove_html_tags` (BeautifulSoup), `sent_tokenize`, o `remove_ner` (uma passada de regex
por span sobre o original todo) e a serializacao da resposta. Medido em 02/09/2026 numa
maquina de ~1.150 chars/s, com `ANONY_TIMEOUT_S=13` e prefixo praticamente constante:

    texto total     parede
     13.920 chars    12,1 s   (coube inteiro)
     41.220          13,8 s
     81.660          14,2 s
    161.160          14,6 s
    320.340          16,2 s

Ou seja 13 s de orcamento seguram a parede abaixo dos 15 s do cliente ate a casa dos
150 mil chars de texto total; acima disso o custo de texto inteiro sozinho passa do teto, e
escolher outro prefixo nao muda isso. Nessa faixa a nota se perde como se perdia antes — a
diferenca e que o servico gasta ~15 s em vez de horas, e o `vazao_chars_s` do /versao cai,
apertando o orcamento sozinho.

Fechar isso pede modelar o custo de texto inteiro (ou um teto de RELOGIO, janelando a
inferencia), e nao um numero diferente aqui.

## Por que a vazao e medida, e nao configurada

Sao ~120 boxes com CPUs que vao do E5420 (2007) ao Xeon Silver 4514Y. Um teto em
caracteres teria de ser calibrado box a box e envelheceria a cada troca de modelo. Medindo
a vazao real, **o mesmo `ANONY_TIMEOUT_S` vale para a frota inteira**: cada box passa a
recusar o que ela, naquela maquina e naquela carga, nao entrega a tempo.

A media e **pessimista de proposito** (`ALFA_LENTO` > `ALFA_RAPIDO`): a curva do E5420 e
superlinear — 724 chars/s em 992 chars, 324 chars/s em 7.936 —, entao uma media simetrica
seria puxada pelos textos curtos e deixaria passar o texto longo que estoura. Reagir rapido
a queda e devagar a subida erra para o lado de recusar cedo demais, que custa uma nota
descartada; o erro oposto custa o laco de reprocessamento descrito acima.

## Sem medicao, nao se corta

Enquanto nao houver nenhuma amostra, `estimativa()` devolve `None` e o pedido **passa
inteiro**. Cortar por um numero que ninguem mediu seria inventar o numero — e a primeira
chamada apos o boot e exatamente quando ele nao existe.

⚠️ O preco disso e que a primeira nota longa depois de cada recreate do container roda sem
teto e pode estourar o cliente. E o buraco que so um teto de RELOGIO fecha (janelar a
inferencia e conferir o tempo entre as janelas); a estimativa, por construcao, nao o fecha.
"""

# Anotacoes preguicosas: o servico roda em 3.13, mas o teste deste modulo tem de rodar
# em qualquer python (o CI e a maquina de quem for mexer), e `float | None` so existe em 3.10+.
from __future__ import annotations

# Peso da amostra nova quando ela indica que a maquina esta MAIS LENTA / mais rapida.
ALFA_LENTO = 0.5
ALFA_RAPIDO = 0.15

# Abaixo disto a amostra e ruido de overhead fixo (parse, tokenize, resposta) e nao mede
# vazao de inferencia: um texto de 20 chars sai em 8 ms e daria 2.500 chars/s de "vazao"
# que nao se sustenta em 8 mil chars.
MIN_CHARS_AMOSTRA = 500


class Medidor:
    """Vazao observada do /clean, em caracteres por segundo."""

    def __init__(self, vazao: float | None = None):
        self.vazao = vazao
        self.amostras = 0

    def registra(self, chars: int, segundos: float) -> None:
        """Incorpora uma execucao concluida. Ignora texto curto e tempo nao positivo."""
        if chars < MIN_CHARS_AMOSTRA or segundos <= 0:
            return
        nova = chars / segundos
        self.amostras += 1
        if self.vazao is None:
            self.vazao = nova
            return
        alfa = ALFA_LENTO if nova < self.vazao else ALFA_RAPIDO
        self.vazao = (1 - alfa) * self.vazao + alfa * nova

    def estimativa(self, chars: int) -> float | None:
        """Segundos previstos para `chars`, ou `None` se ainda nao ha vazao medida."""
        if self.vazao is None or self.vazao <= 0:
            return None
        return chars / self.vazao


def cabe_no_orcamento(chars: int, estimativa_s: float | None, timeout_s: float) -> bool:
    """`False` so quando ha estimativa E ela estoura o orcamento.

    Orcamento desligado (`timeout_s <= 0`) ou sem estimativa passam — a ausencia de medicao
    nunca vira o veredito contrario.
    """
    if timeout_s <= 0 or estimativa_s is None:
        return True
    return estimativa_s <= timeout_s


def motivo_recusa(chars: int, estimativa_s: float, timeout_s: float, vazao: float) -> str:
    """Mensagem da recusa: tudo que o operador precisa para decidir, sem abrir o container."""
    return (
        f"texto de {chars} chars nao cabe no orcamento desta instalacao: "
        f"estimativa {estimativa_s:.1f}s contra ANONY_TIMEOUT_S={timeout_s:g}s "
        f"(vazao medida {vazao:.0f} chars/s). Nada foi processado. "
        f"Aumente o Read Timeout do cliente e o ANONY_TIMEOUT_S juntos, "
        f"ou destine esta carga a uma maquina mais rapida."
    )


def chars_que_cabem(vazao: float | None, timeout_s: float) -> int | None:
    """Maior texto que cabe no orcamento nesta maquina, em chars. `None` = sem teto.

    Inverso EXATO de `cabe_no_orcamento`: `chars / vazao <= timeout_s` equivale a
    `chars <= vazao * timeout_s`. Isso e o que faz o modo `parcial` ler o maximo que o modo
    `recusa` teria aceitado, em vez de um pedaco escolhido por outra regra — e o que permite
    testar as duas decisoes contra a mesma medicao.
    """
    if timeout_s <= 0 or vazao is None or vazao <= 0:
        return None
    return int(vazao * timeout_s)


def frases_que_cabem(frases, limite: int | None) -> int:
    """Quantas frases do INICIO cabem em `limite` chars. Sem limite, todas.

    Corta em fronteira de frase, nunca no char exato: nome partido ao meio nao e nome para o
    modelo, e a metade que sobra iria para o texto nao lido sem que a contagem acusasse.

    Devolve 0 quando nem a primeira frase cabe — e o caso em que o chamador tem de recusar,
    e nao devolver 200 com o texto inteiro em claro.
    """
    if limite is None:
        return len(frases)
    total = 0
    for i, frase in enumerate(frases):
        total += len(frase)
        if total > limite:
            return i
    return len(frases)


def aviso_parcial(
    chars_nao_lidos: int, chars_total: int, timeout_s: float, vazao: float | None
) -> str:
    """Mensagem do 200 parcial. Diz o que NAO foi redigido, que e o que muda a conduta.

    Fala em chars NAO lidos e no total, os dois exatos. "Chars lidos" seria a diferenca
    entre o texto e a soma das frases nao lidas, e essa conta carrega TODO o espaco entre
    frases do documento para o lado lido: num texto de frases curtas ela quase dobra o
    numero (medido: 2.121 para um prefixo de 1.121 chars).
    """
    cabe = chars_que_cabem(vazao, timeout_s)
    medida = f"{vazao:.0f}" if vazao else "?"
    return (
        f"redacao PARCIAL: os {chars_nao_lidos} chars finais de {chars_total} nao foram "
        f"lidos e voltam como no original — podem conter nome em claro. "
        f"Cabem ~{cabe if cabe is not None else '?'} chars no "
        f"ANONY_TIMEOUT_S={timeout_s:g}s desta instalacao (vazao medida {medida} chars/s). "
        f"Aumente o Read Timeout do cliente e o ANONY_TIMEOUT_S juntos, "
        f"ou destine esta carga a uma maquina mais rapida."
    )
