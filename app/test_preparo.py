"""Testes do plain que vai ao modelo. Rodam SEM o modelo, sem a imagem e sem bs4.

O defeito que motivou `preparo.py` e o `get_text()` sem separador fundindo o fim de um
elemento no comeco do outro. Os nomes aqui sao inventados; o que se preserva do caso real e
o FORMATO (onde cai a tag, a entidade, a quebra). Rode com `python3 app/test_preparo.py`.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preparo import CANARIO, plain_do_html

NBSP = "\xa0"


def test_tag_entre_elementos_vale_um_espaco():
    # `get_text()` devolvia 'ENFERMAGEMFulana Beltrano, 74 anos' — forma que nao existe no HTML
    # e que a redacao nunca casa. Aqui a fronteira sobrevive.
    p = plain_do_html("<p>ENFERMAGEM</p><p>Fulana Beltrano, 74 anos</p>")
    assert "ENFERMAGEMFulana" not in p
    assert "Fulana Beltrano, 74 anos" in p


def test_tag_inline_no_meio_do_nome_tambem_separa():
    # `<span>B</span>eltrana` — o hospital formata a inicial. O plain fica 'B eltrana', o
    # modelo marca 'eltrana Sicrano', e a redacao casa 'eltrana Sicrano' no HTML. Antes: o
    # get_text() dava 'Beltrana Sicrano', que NAO existe no HTML, e nada era redigido.
    p = plain_do_html("<strong><span>B</span>eltrana Sicrano, 76 anos</strong>")
    assert "eltrana Sicrano, 76 anos" in p


def test_br_e_quebra_de_linha_viram_fronteira_de_frase():
    p = plain_do_html("Sem queixas<br/>Nega alergias.\nAceita dieta")
    # a quebra fica (o runtime faz igual); o que muda e o `. ` antes dela
    assert p == "Sem queixas Nega alergias.. \nAceita dieta"


def test_entidade_decodificada_como_o_bs4_fazia():
    p = plain_do_html("Fulana&nbsp;Beltrano &gt; 140 &amp; HAS")
    assert f"Fulana{NBSP}Beltrano > 140 & HAS" == p


def test_interrogacao_e_barra_deixam_de_virar_ponto():
    # A classe `[\r?\n|\r]` do replace_breaklines antigo casava `?` e `|` literais.
    p = plain_do_html("Alguem lhe acompanhara? Sim | Nao")
    assert p == "Alguem lhe acompanhara? Sim | Nao"


def test_canario_tem_as_quatro_formas():
    p = plain_do_html(CANARIO)
    # a tag `</b>` vira espaco, entao 'Fulana' e NBSP+'Beltrano' ficam separados por ele
    assert "ENFERMAGEMFulana" not in p and f"Fulana {NBSP}Beltrano" in p
    assert "> 140" in p and "Acompanhada?" in p


def test_nao_importa_bs4_nem_o_runtime():
    assert "bs4" not in sys.modules and "anony_onnx_runtime" not in sys.modules


if __name__ == "__main__":
    testes = [f for n, f in sorted(globals().items()) if n.startswith("test_")]
    for t in testes:
        t()
        print("ok ", t.__name__)
    print(f"{len(testes)} testes passaram")
