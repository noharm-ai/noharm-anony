"""Testes da redacao. Rodam SEM o modelo e sem a imagem.

`redacao.py` nao importa o runtime nem bs4 de proposito: e o unico jeito de o CI conferir
esta decisao antes do build de 200 MB. Rode com `python3 app/test_redacao.py`.

A FORMA de cada defeito foi medida em 170 evolucoes do `doamor` em 2026-09-12 (as pendentes
do dia, pacote o1.3). **Os nomes proprios aqui sao inventados** — o que se preserva do caso
real e so o formato do defeito (onde cai o NBSP, onde cai a tag, onde cai a pontuacao), que
e o que o codigo tem de tratar. Se a substituicao mudar, o teste falha contra o caso que
motivou o codigo, sem que nenhum dado de paciente precise viver no repositorio.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from redacao import padrao_do_span, redige, trechos_que_casam

NBSP = " "
ZWSP = "​"


def test_o_caso_de_sempre_continua_igual():
    """Espaco comum, caixa qualquer, todas as ocorrencias: nada disso muda."""
    assert redige(["Maria Angelica"], "a Maria Angelica e a maria angelica") == "a *** e a ***"


def test_nbsp_no_meio_do_nome_era_vazamento_silencioso():
    """5 de 28 spans de producao do doamor tinham essa divergencia; 2 eram nome.

    O runtime junta os TOKENS com espaco comum, o hospital digitou `\\xa0`, e o
    `re.escape(" ")` do servico 1.4 nao casava — o nome ficava em claro sem log nenhum.
    """
    texto = f"Anexo {NBSP}  Marlene Ferraz Tondo assinou"
    assert redige(["Marlene Ferraz Tondo"], texto) == "Anexo    *** assinou"
    # e a forma suja que o modelo emitiu naquele documento tambem casa
    assert "***" in redige([f"Anexo           Marlene Ferraz Tondo"], texto)


def test_espaco_exotico_qualquer():
    """`\\s` de padrao str ja cobre NBSP, espaco fino e ideografico — o teste trava isso."""
    for esp in (" ", " ", " ", "　", "\n", "  \t "):
        assert redige(["Ana Paula"], f"x Ana{esp}Paula y") == "x *** y", repr(esp)


def test_zero_width_colado_no_nome():
    """O flair remove o invisivel antes de tokenizar e FUNDE as metades: o span vira uma
    string que nao existe no texto. Conhecido desde 2026-08-31 e nunca consertado na
    redacao — aqui sai de graca."""
    assert redige(["PacienteMaria"], f"leito Paciente{ZWSP}Maria 12") == "leito *** 12"
    assert redige(["Ana Paula"], f"x Ana{ZWSP} Paula y") == "x *** y"


def test_borda_de_pontuacao_nunca_casava():
    """`\\b` exige transicao palavra/nao-palavra: span que comeca ou termina em pontuacao
    nao casava NUNCA. `Everton,` e `(  Rosangela` sao formas reais do mesmo dia."""
    assert redige(["Everton,"], "Enf. Everton, presente") == "Enf. *** presente"
    assert redige(["(  Rosangela"], "avaliada (  Rosangela ) ontem") == "avaliada *** ) ontem"


def test_o_b_continua_valendo_na_borda_alfanumerica():
    """O `\\b` nao foi removido, so condicionado a borda: substring de palavra maior nao e
    redigida, que e o que ele protege."""
    assert redige(["Ana"], "Ana e Anabela e ANA") == "*** e Anabela e ***"
    assert redige(["Silva"], "Silvano nao e Silva") == "Silvano nao e ***"


def test_span_sem_alfanumerico_nao_redige_nada():
    """Com ANONY_FILTROS=0 o servico redige TUDO que o modelo marca. Padrao sem ancora
    casaria posicao vazia no texto inteiro — o guard existe por isso."""
    assert padrao_do_span("...") is None
    assert padrao_do_span("  ") is None
    assert redige(["...", "  "], "nada ... muda  aqui") == "nada ... muda  aqui"


def test_metacaractere_no_nome_continua_literal():
    """`re.escape` por caractere: nome com pontuacao de regex nao vira padrao."""
    assert redige(["D'Avila (Jr.)"], "o D'Avila (Jr.) veio") == "o *** veio"
    assert redige(["a.b"], "axb nao casa, a.b casa") == "axb nao casa, *** casa"


def test_html_DENTRO_do_nome_redige_as_duas_metades():
    """A forma inteira nao casa (a tag esta no meio) e tolerar `<b>` no padrao redigiria a
    MARCACAO junto, mudando o HTML entregue. O fallback resolve sem isso: as duas metades
    existem sozinhas, e as duas sao redigidas. Sem ele, o sobrenome ficava em claro."""
    assert redige(["Maria Angelica"], "a Maria<b> </b>Angelica fim") == "a ***<b> </b>*** fim"
    assert redige(["Maria Angelica"], "a Maria<b> </b>Angelica fim",
                  por_pedacos=False) == "a Maria<b> </b>Angelica fim"


def test_fallback_recupera_nome_que_o_span_cruzando_TAG_deixava_em_claro():
    """O caso real de 2026-09-12: o modelo le o texto sem HTML, onde a tag virou espaco, e
    emite UM span por cima da fronteira de paragrafo. A forma inteira nao casa no original
    — que ainda tem a tag — e o nome ficava 100% em claro."""
    original = '<p><b>Anexo</b></p><p style="x"><b>Marlene Ferraz Tondo COREN 000000</b></p>'
    # O `get_text()` do servico junta os dois paragrafos com UM espaco: e assim que o span
    # chega, e por isso que o fallback nao pode depender de corrida de espacos.
    span = "Anexo Marlene Ferraz Tondo"
    assert redige([span], original, por_pedacos=False) == original, "sem fallback, nada acontece"
    com = redige([span], original)
    assert "Marlene Ferraz Tondo" not in com, com
    assert trechos_que_casam(span, original) == ["Anexo", "Marlene Ferraz Tondo"]


def test_fallback_nao_dispara_quando_a_forma_inteira_casa():
    """So age onde hoje nao acontece nada. Span que casa e redigido e pronto — o token
    solto NAO e redigido por fora."""
    texto = "Queda            Flebite e depois Queda: alto risco"
    assert redige(["Queda            Flebite"], texto) == "*** e depois Queda: alto risco"


def test_fallback_decompoe_do_maior_para_o_menor():
    """Guloso: o maior trecho primeiro, depois o que sobra dos dois lados. E o preco do
    fallback, escrito — span que e so lixo apaga termo clinico em toda a nota."""
    texto = "<p>Laranja</p><p>Amarelo Verde Azul</p> e Laranja de novo"
    assert trechos_que_casam("Laranja Amarelo Verde Azul", texto) == ["Laranja", "Amarelo Verde Azul"]
    com = redige(["Laranja Amarelo Verde Azul"], texto)
    assert "Laranja" not in com and "Amarelo" not in com, com


def test_fallback_ignora_span_de_um_nucleo_so():
    """`Everton,` nao casando seria caso de borda, ja resolvido acima; repetir por pedacos so
    abriria espaco para redigir pontuacao solta."""
    assert redige(["Ausente"], "nada aqui") == "nada aqui"


def test_knob_desliga_o_fallback():
    original = "<p>Anexo</p><p>Marlene Ferraz Tondo</p>"
    span = "Anexo Marlene Ferraz Tondo"
    assert redige([span], original, por_pedacos=False) == original
    assert redige([span], original) != original


if __name__ == "__main__":
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in testes:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(testes)} testes passaram")
