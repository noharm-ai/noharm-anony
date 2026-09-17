"""O texto que vai ao modelo — e por que ele NAO e mais o `get_text()` do BeautifulSoup.

Ate o servico 1.5 o plain era `soup.get_text()` SEM separador. Isso apaga a fronteira entre
dois elementos: `<p>ENFERMAGEM</p><p>Fulana Beltrano, 74 anos</p>` vira `ENFERMAGEMFulana
Beltrano, 74 anos`. O modelo ainda marca o nome, mas emite uma FORMA que nao existe no HTML
(`ENFERMAGEMFulana Beltrano`, `Sicrana Beltrano FulanoIdade`, `Fulano8a`), e a redacao — que
casa por forma sobre o original — nao encontra nada. Quando o sobrenome sai como span
separado ele e redigido e o primeiro nome colado sobrevive: e o `Fulana ***, 74 anos` que
aparecia em dois hospitais com o pacote mais novo instalado.

Os nomes proprios dos exemplos deste modulo (e dos testes) sao INVENTADOS. O que se
preserva do caso real e so a FORMA do defeito — onde a tag cai, onde o nome funde, onde
entra o NBSP —, que e o que a regua mede. Mesma convencao do `test_redacao.py`.

Medido em 16/09/2026, textos do dia ainda sem redacao do servidor, pacote o1.3, reproduzindo
o `/clean` da 1.4 e da 1.5 em maquina local:

  schema          spans do modelo   a 1.4 nao redigia   por fusao de tag   a 1.5 recupera
  hospital A (180)      45               38 (84%)              30                37
  hospital B (158)      37               33 (89%)              28                32

A 1.5 recupera quase tudo pelo fallback por pedacos, mas so o que ainda existe como palavra
inteira no texto: `ENFERMAGEMFulana` e `Fulano8a` nao se decompoem. O conserto e na origem —
dar ao modelo um plain em que a tag vale um espaco.

Esta funcao e **byte a byte** a `to_plain` do `anony_onnx_runtime.py` e do `anony-frota.py`
(o job que redige a mesma coluna no servidor). Ou seja: e o texto sobre o qual TODA regua
desta linha foi medida; o `get_text()` era o unico caminho que o modelo via e ninguem media.
Copia em vez de import porque o runtime mora no pacote (`ANONY_PACOTE_DIR`) e este modulo
tem de rodar no CI sem pacote e sem bs4 — `main.py` confere as duas num canario ao carregar.

Duas mudancas que vem juntas e nao sao detalhe:

  - **`(\\r?\\n|\\r)` no lugar de `[\\r?\\n|\\r]`.** A classe de caracteres do
    `replace_breaklines` antigo casava tambem `?` e `|` literais: `acompanhara?` virava
    `acompanhara. ?`. O plain deixa de inventar fronteira de frase em pergunta;
  - **`html.unescape` em vez do decode do bs4.** Para entidade e o mesmo resultado
    (`&nbsp;` -> NBSP, `&gt;` -> `>`); a diferenca e que o regex NAO descarta `<script>`,
    `<style>` nem comentario — nota clinica nao tem nenhum dos tres, e o `str(soup)` sobre o
    qual a redacao roda continua sendo o do bs4.

`ANONY_PLAIN=bs4` volta ao `get_text()` da 1.5 sem rebuild, e o modo em uso sai no `/versao`.
"""
import html
import re

RE_TAG = re.compile(r"<.*?>")
RE_BR = re.compile(r"(\r?\n|\r)")


def plain_do_html(texto: str) -> str:
    """Tag -> espaco, quebra de linha -> `. ` + quebra, entidades decodificadas."""
    t = RE_BR.sub(r". \1", texto)
    t = RE_TAG.sub(" ", t)
    return html.unescape(t)


# O canario que `main.py` roda contra o `to_plain` do runtime ao carregar o pacote: cobre
# tag entre elementos, `<br/>`, entidade e quebra de linha. Divergir aqui e sinal de que uma
# das duas copias mudou sozinha.
CANARIO = ("<p>ENFERMAGEM</p><p><b>Fulana</b>&nbsp;Beltrano, 74 anos.<br/>HAS &gt; 140\n"
           "Acompanhada?</p>")
