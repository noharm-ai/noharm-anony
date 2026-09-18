"""Testes da blocklist extra (serviço 1.7). Rodam SEM o modelo e sem a imagem.

`blocklist.py` não importa o runtime nem bs4 de propósito: é o que permite o CI conferir a
lista e o filtro antes do build de 200 MB. Rode com `python3 app/test_blocklist.py`.

**Os nomes próprios aqui são inventados.** O que se testa é a regra — forma inteira, em
`casefold`, nunca substring — e três invariantes do arquivo versionado, que é público.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blocklist import CAMINHO_PADRAO, carrega, e_bloqueado, filtra  # noqa: E402


def test_o_arquivo_versionado_carrega_e_nao_esta_vazio():
    bl = carrega()
    assert len(bl) >= 30, len(bl)
    for forma in ("higiene oral", "eficacia", "rankin", "calibre jelco"):
        assert forma in bl, forma


def test_comentario_e_linha_vazia_sao_ignorados_e_a_forma_sai_em_casefold():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write("# cabeçalho\n\n  Higiene Oral  \nEFICÁCIA # comentário no fim\n\n")
        caminho = fh.name
    try:
        assert carrega(caminho) == {"higiene oral", "eficácia"}
    finally:
        os.unlink(caminho)


def test_arquivo_ausente_e_lista_vazia_e_nao_erro():
    assert carrega("/nao/existe/blocklist.txt") == set()


def test_a_comparacao_e_por_forma_inteira_e_nunca_por_substring():
    bl = {"higiene", "calibre"}
    assert e_bloqueado("Higiene", bl)
    assert e_bloqueado("  HIGIENE ", bl)
    assert not e_bloqueado("Higienópolis", bl), "substring não conta"
    assert not e_bloqueado("Higiene Oral", bl), "a forma inteira é outra"
    assert not e_bloqueado("Calibre 22", bl)


def test_filtra_derruba_so_a_forma_listada_e_preserva_a_ordem():
    bl = {"eficacia", "grata"}
    spans = [{"texto": "Joana Prates"}, {"texto": "Eficacia"}, {"texto": "grata"},
             {"texto": "Ivo Prates"}]
    assert [s["texto"] for s in filtra(spans, bl)] == ["Joana Prates", "Ivo Prates"]
    assert filtra([], bl) == []


def test_o_arquivo_publico_nao_tem_forma_com_cara_de_nome_de_pessoa():
    """Este repositório é público. A regra do arquivo é: forma de NÃO-NOME medida em
    produção — nada com leitura de nome de pessoa real, nem hospital, cidade ou paciente.
    Um teste não sabe julgar semântica, mas segura as duas violações mais fáceis de
    cometer sem querer: forma com duas ou mais palavras capitalizadas (a assinatura de
    `Nome Sobrenome`) e linha que escapou ao `casefold`."""
    with open(CAMINHO_PADRAO, encoding="utf-8") as fh:
        linhas = [l.split("#", 1)[0].strip() for l in fh]
    formas = [l for l in linhas if l]
    for f in formas:
        assert f == f.casefold(), f"forma fora do casefold no arquivo: {f!r}"
        assert len(f.split()) <= 4, f"forma longa demais para ser rótulo ou termo: {f!r}"
    assert len(formas) == len(set(formas)), "forma repetida no arquivo"


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"FAIL {nome}: {e}")
    sys.exit(1 if falhas else 0)
