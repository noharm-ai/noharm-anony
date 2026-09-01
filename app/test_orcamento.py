"""Testes do orcamento de tempo. Rodam SEM o modelo e sem a imagem.

`orcamento.py` nao importa nada do runtime de proposito: e o unico jeito de o CI conferir
esta decisao sem baixar o pacote de 200 MB e sem ter CPU para inferencia. Rode com
`python3 app/test_orcamento.py`.

Os numeros vem de medicao real em 2026-09-01 (duas boxes da frota), nao de exemplo
inventado: se a matematica mudar, o teste tem de falhar contra o caso que motivou o codigo.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orcamento import Medidor, cabe_no_orcamento, motivo_recusa, MIN_CHARS_AMOSTRA

# (chars, segundos) medidos no Xeon E5420 de 2007 — a curva e SUPERLINEAR.
BOX_LENTA = [(992, 1.37), (1984, 2.77), (3968, 6.30), (5952, 9.66), (7936, 24.50)]
# Mesma sonda num Xeon moderno.
BOX_RAPIDA = [(9196, 1.80), (31516, 5.55), (76156, 12.98)]


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


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in testes:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(testes)} testes passaram")
