"""Testes do orcamento de tempo. Rodam SEM o modelo e sem a imagem.

`orcamento.py` nao importa nada do runtime de proposito: e o unico jeito de o CI conferir
esta decisao sem baixar o pacote de 200 MB e sem ter CPU para inferencia. Rode com
`python3 app/test_orcamento.py`.

Os numeros vem de medicao real em 2026-09-01 (duas boxes da frota), nao de exemplo
inventado: se a matematica mudar, o teste tem de falhar contra o caso que motivou o codigo.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orcamento import (
    Medidor,
    aviso_parcial,
    cabe_no_orcamento,
    chars_que_cabem,
    frases_que_cabem,
    motivo_recusa,
    MIN_CHARS_AMOSTRA,
)

# (chars, segundos) medidos no Xeon E5420 de 2007 — a curva e SUPERLINEAR.
BOX_LENTA = [(992, 1.37), (1984, 2.77), (3968, 6.30), (5952, 9.66), (7936, 24.50)]
# Mesma sonda num Xeon moderno.
BOX_RAPIDA = [(9196, 1.80), (31516, 5.55), (76156, 12.98)]
# A instalacao que motivou o modo `parcial` (2026-09-02): vCPU "Common KVM processor" que
# nao expoe sse4_2/avx/avx2, entao o onnxruntime cai no kernel generico. `/versao` reportou
# 983 chars/s sobre 2.406 amostras, com ANONY_TIMEOUT_S=13. A maior nota do dia anterior
# tinha 78.657 chars.
VAZAO_SEM_AVX = 983.0
TIMEOUT_SEM_AVX = 13.0
MAIOR_NOTA_SEM_AVX = 78657


def test_sem_amostra_nao_recusa():
    """Ausencia de medicao nunca vira o veredito contrario: passa e aprende com o pedido."""
    m = Medidor()
    assert m.estimativa(9000) is None
    assert cabe_no_orcamento(9000, m.estimativa(9000), 15) is True


def test_orcamento_desligado_passa_qualquer_coisa():
    m = Medidor()
    for c, s in BOX_LENTA:
        m.registra(c, s)
    assert cabe_no_orcamento(999999, m.estimativa(999999), 0) is True


def test_texto_curto_nao_vira_amostra():
    """Overhead fixo daria uma vazao fantasiosa que nao se sustenta em texto longo."""
    m = Medidor()
    m.registra(MIN_CHARS_AMOSTRA - 1, 0.008)
    assert m.vazao is None and m.amostras == 0


def test_box_rapida_aceita_nota_grande():
    m = Medidor()
    for c, s in BOX_RAPIDA:
        m.registra(c, s)
    # 9 mil chars levam ~1,8 s ali: tem de caber com folga num orcamento de 12 s.
    assert cabe_no_orcamento(9196, m.estimativa(9196), 12) is True


def test_box_lenta_recusa_o_texto_que_estourava():
    """O caso que motivou o codigo: 7.936 chars levaram 24,5 s contra Read Timeout de 15 s."""
    m = Medidor()
    for c, s in BOX_LENTA:
        m.registra(c, s)
    assert cabe_no_orcamento(7936, m.estimativa(7936), 15) is False
    # ...e a nota curta do mesmo cliente continua passando: recusar TUDO seria pior que nada.
    assert cabe_no_orcamento(102, m.estimativa(102), 15) is True


def test_media_e_pessimista():
    """Queda de vazao pesa mais que subida — a curva superlinear exige errar para o lado
    de recusar cedo. Simetrico, o texto longo passaria e estouraria o cliente."""
    m = Medidor(vazao=1000.0)
    m.registra(1000, 2.0)  # 500 chars/s: metade
    caiu = m.vazao
    m2 = Medidor(vazao=1000.0)
    m2.registra(2000, 1.0)  # 2000 chars/s: dobro
    subiu = m2.vazao
    assert (1000 - caiu) > (subiu - 1000)


def test_motivo_diz_o_que_o_operador_precisa():
    msg = motivo_recusa(7936, 16.4, 15.0, 485.0)
    for pedaco in ("7936", "16.4", "ANONY_TIMEOUT_S=15", "485", "Nada foi processado"):
        assert pedaco in msg, f"faltou {pedaco!r} em: {msg}"


def test_chars_que_cabem_e_o_inverso_exato_da_recusa():
    """A propriedade que liga os dois modos: o prefixo lido no `parcial` e o MAXIMO que o
    `recusa` teria aceitado. Se as duas contas divergirem, `parcial` vira outra regra."""
    m = Medidor()
    for c, s in BOX_LENTA:
        m.registra(c, s)
    limite = chars_que_cabem(m.vazao, 15)
    assert cabe_no_orcamento(limite, m.estimativa(limite), 15) is True
    assert cabe_no_orcamento(limite + 1, m.estimativa(limite + 1), 15) is False


def test_sem_orcamento_ou_sem_medicao_nao_ha_teto():
    """Mesma assimetria do resto do modulo: ausencia nunca vira um numero inventado."""
    assert chars_que_cabem(1000.0, 0) is None
    assert chars_que_cabem(None, 15) is None
    assert chars_que_cabem(0.0, 15) is None
    # Sem teto, o prefixo e o texto inteiro.
    assert frases_que_cabem(["a" * 100] * 5, None) == 5


def test_prefixo_corta_em_fronteira_de_frase():
    """Nunca no char exato: nome partido ao meio nao e nome para o modelo."""
    frases = ["a" * 100, "b" * 100, "c" * 100]
    assert frases_que_cabem(frases, 250) == 2
    assert frases_que_cabem(frases, 300) == 3
    assert frases_que_cabem(frases, 100) == 1


def test_nem_a_primeira_frase_cabe_devolve_zero():
    """O piso do modo `parcial`: zero frase lida faz o chamador RECUSAR. Um 200 com o texto
    inteiro em claro nao e redacao parcial, e nenhum rotulo o torna aceitavel."""
    assert frases_que_cabem(["x" * 5000], 1200) == 0
    assert frases_que_cabem([], 1200) == 0


def test_box_sem_avx_le_a_fatia_que_cabe_em_vez_de_perder_a_nota():
    """O caso que motivou o modo: nesta maquina a nota de 78.657 chars e recusada inteira,
    e o `parcial` entrega os ~16% iniciais redigidos em vez de nada."""
    limite = chars_que_cabem(VAZAO_SEM_AVX, TIMEOUT_SEM_AVX)
    assert limite == 12779
    assert cabe_no_orcamento(MAIOR_NOTA_SEM_AVX, MAIOR_NOTA_SEM_AVX / VAZAO_SEM_AVX,
                             TIMEOUT_SEM_AVX) is False
    # Frases de ~1.000 chars: cabem 12 das 78, e as outras 66 voltam como original.
    frases = ["z" * 1000] * 78
    lidas = frases_que_cabem(frases, limite)
    assert lidas == 12
    nao_lidos = sum(len(f) for f in frases[lidas:])
    assert nao_lidos == 66000


def test_aviso_diz_o_que_NAO_foi_redigido():
    """A conduta de quem le muda pelo trecho em claro, nao pelo trecho redigido."""
    msg = aviso_parcial(65878, 78657, 13.0, 983.0)
    for pedaco in ("PARCIAL", "65878", "78657", "12779", "nome em", "ANONY_TIMEOUT_S=13", "983"):
        assert pedaco in msg, f"faltou {pedaco!r} em: {msg}"


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in testes:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(testes)} testes passaram")
