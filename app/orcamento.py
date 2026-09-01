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

## Sem medicao, nao se recusa

Enquanto nao houver nenhuma amostra, `estimativa()` devolve `None` e o pedido **passa**.
Recusar por um numero que ninguem mediu seria inventar o numero — e a primeira chamada apos
o boot e exatamente quando ele nao existe.
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
