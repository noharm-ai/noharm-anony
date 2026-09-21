import os, re, sys, tempfile, time, traceback, unicodedata, subprocess
from bs4 import BeautifulSoup
from nltk.tokenize import sent_tokenize

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette import status

from redacao import redige
from preparo import CANARIO, plain_do_html
from blocklist import carrega as carrega_blocklist, filtra as filtra_blocklist
from orcamento import (
    Medidor,
    aviso_parcial,
    cabe_no_orcamento,
    chars_que_cabem,
    frases_que_cabem,
    motivo_recusa,
)

# Teto do modo `frase`. O nome diz tempo e o efeito e TAMANHO: no guard la embaixo o termo
# `sent_length` (chars/100) domina o de relogio, entao o corte cai por volta de
# `MAX_TIME * 100` caracteres em qualquer maquina. Fica configuravel para nao exigir rebuild,
# com o nome de sempre para nao quebrar quem ja o conhece — mas leia `ANONY_MAX_TIME=20`
# como "teto de ~2.000 caracteres".
MAX_TIME = float(os.environ.get("ANONY_MAX_TIME", "20"))

# Paciencia do CLIENTE, em segundos. **Ligado por default**, como o `MAX_TIME` acima: sem
# orcamento, o texto que passa do Read Timeout do `InvokeHTTP` (15 s em 86 de 92
# processadores medidos) e descartado pelo cliente em SILENCIO, e nenhuma instalacao escolheu
# isso — era so o que acontecia. `0` desliga, para quem chama o /clean de outro lugar.
#
# 13 s e nao 15: o orcamento cobre a inferencia, e rede e serializacao ainda vem por cima.
# Ajuste junto com o Read Timeout do cliente, e sempre ABAIXO dele. Ver `app/orcamento.py`
# para por que estimar em vez de interromper, e por que a vazao e medida.
TIMEOUT_S = float(os.environ.get("ANONY_TIMEOUT_S", "13"))

# O que fazer com o texto que NAO cabe no orcamento. **`parcial` por default**: le o prefixo
# que cabe, redige so ele e devolve o resto como original, com 200 e com o quanto ficou por
# ler DITO na resposta. `recusa` volta ao 413 com nada processado, para quem prefere nao
# gravar nota meio redigida e CONSEGUE reprocessar a recusada.
#
# O default e `parcial` porque a alternativa real nao e "nota inteira redigida", e sim nota
# nenhuma: o flow auto-termina o `Failure` do InvokeHTTP e o cursor nao volta. O piso ("nem
# a primeira frase cabe" ainda recusa) e o racional estao em `app/orcamento.py`.
ORCAMENTO = os.environ.get("ANONY_ORCAMENTO", "parcial")
PARCIAL = ORCAMENTO == "parcial"

medidor = Medidor()

# O modelo agora e ONNX e roda sem flair, sem torch e sem CUDA. O pacote baixado no build
# traz o proprio runtime, que faz a tokenizacao, a janela de subtokens e a decodificacao
# BIOES; o import e por caminho porque a pasta tem hifen no nome.
PACOTE_DIR = os.environ.get("ANONY_PACOTE_DIR", "/app/noharm-anony-onnx")
sys.path.insert(0, PACOTE_DIR)
from anony_onnx_runtime import Pacote  # noqa: E402

# --- as duas chaves que decidem a SEMANTICA, e nao o motor ----------------------------
# Este servico sempre prediu frase ISOLADA e redigiu TUDO que o modelo marcou. O runtime do
# pacote sabe fazer as duas coisas de outro jeito: dar ao modelo as palavras vizinhas como
# contexto (que e como o modelo foi treinado) e descartar span de baixa confianca ou que
# nao tenha forma de nome. As duas mudam o texto redigido MAIS que a troca de motor.
#
# `CONTEXTO` mudou de `frase` para `documento` COM MEDICAO, e ela e o motivo desta versao
# existir. Em 817 evolucoes clinicas reais reservadas para avaliacao (1.572 nomes), pelo
# proprio /clean deste servico:
#
#     modo         nomes removidos      precisao por ocorrencia
#     frase              65,14%                 76,89%
#     documento          96,63%                 90,98%
#
# A diferenca NAO e o modelo: dos 548 nomes que o modo `frase` deixa em claro, **519 estao
# em trecho que o servico nunca leu** e so 29 sao erro de modelo. A causa e o orcamento
# MAX_TIME abaixo, cujo termo `sent_length` vira um teto de ~2.000 caracteres — e num
# documento cujo primeiro paragrafo ja passa disso, a nota sai INTEIRA sem redigir nada
# (medido: 14 ms de resposta num texto de 6.220 caracteres).
#
# O preco e latencia: ~50 ms passam a ~400 ms numa nota de 8 mil caracteres. Num PUT
# sincrono isso e aceitavel, e e o que compra 31 pontos de recall.
#
# `ANONY_CONTEXTO=frase` volta ao comportamento anterior sem rebuild.
CONTEXTO = os.environ.get("ANONY_CONTEXTO", "documento")
# Tres modos, e a diferenca entre eles e o que se DEIXA de redigir:
#   `blocklist` (default desde a 1.7) — tudo, MENOS a forma que esta na blocklist (a do
#                    manifesto do pacote unida a `app/blocklist.txt`). Sem corte de
#                    confianca e sem exigencia de maiuscula: redige menos so onde a
#                    medicao diz que nao havia nome (0 nomes em 1.976 spans arbitrados e
#                    6.457 labels de treino), e continua redigindo todo o resto;
#   `0`            — tudo que o modelo marca, o comportamento de 1.0 a 1.6;
#   `1`            — os filtros do runtime (confianca minima + forma de nome) mais a
#                    blocklist extra. Deixa de redigir nome escrito todo em minuscula.
# Racional e procedencia da lista: `app/blocklist.py`. `ANONY_FILTROS=0` volta a 1.6.
FILTROS = os.environ.get("ANONY_FILTROS", "blocklist")
if FILTROS not in ("0", "1", "blocklist"):
    raise SystemExit(f"ANONY_FILTROS={FILTROS!r}: os valores sao 0, 1 ou blocklist")
FILTROS_RUNTIME = FILTROS == "1"
FILTROS_BLOCKLIST = FILTROS in ("1", "blocklist")
# Fallback da redacao, LIGADO por default. So age onde hoje nao acontece nada: span cuja
# forma inteira nao casa no original — o caso do span que cruza uma tag HTML, porque o
# modelo le o texto sem tags e as ve como espaco. Custo medido: 1,5 termo clinico redigido
# por nome recuperado. `ANONY_REDACAO_PEDACOS=0` volta a so redigir a forma inteira. O
# racional e os numeros estao em `app/redacao.py`.
REDACAO_PEDACOS = os.environ.get("ANONY_REDACAO_PEDACOS", "1") == "1"

# O plain que o modelo le. Ate a 1.5 era `soup.get_text()` SEM separador, que funde o fim de
# um elemento no comeco do outro (`ENFERMAGEMFulana Beltrano`): o modelo marca, a forma nao
# existe no HTML, a redacao nao casa — 84-89% dos spans que o modelo achava em dois hospitais
# com o pacote atual ficavam em claro. `espaco` (default) e o `to_plain` do runtime e do
# anony-frota, o texto sobre o qual toda regua foi medida; `bs4` e o comportamento da 1.5.
# Numeros e racional em `app/preparo.py`.
PLAIN = os.environ.get("ANONY_PLAIN", "espaco")
THREADS = int(os.environ.get("ANONY_THREADS", "0")) or None


class PacoteFrase(Pacote):
    """Trata o texto recebido como UMA frase, sem reparti-lo de novo.

    O runtime separa frases com o `sent_tokenize` em portugues; este servico ja separou as
    dele com o `sent_tokenize` default (ingles) e passa uma por chamada. Sem esta subclasse
    o pacote poderia repartir de novo — e ai colocaria contexto entre os pedacos, que e
    exatamente o que o modo `frase` nao quer.
    """

    def frases(self, plain):
        return [plain] if plain.strip() else []

# Versao do SERVICO — o codigo deste repositorio, e nao o modelo. O `pacote` que sai ao
# lado dela no /versao vem do manifesto do tar baixado no build (`ARG ANONY_PACOTE`) e
# versiona o ONNX; sao coisas que mudam em ritmos diferentes e por PRs diferentes. Ate aqui
# so o modelo tinha versao, entao uma mudanca de comportamento do /clean chegava na frota
# indistinguivel da anterior — que e exatamente o que o /versao existe para impedir.
#
# Suba isto em todo PR que mude o que o /clean DEVOLVE (campo novo, status diferente,
# decisao nova). Mudanca so de dependencia ou de build nao precisa.
#
# A 1.7.1 nao muda contrato nenhum — nenhum campo, nenhum status, nenhum knob novo. Ela
# entra aqui porque conserta o texto que o /clean DEVOLVIA em pedido RTF concorrente (o
# arquivo fixo do `rtf_to_text`, que trocava a nota de um paciente pela de outro), e sem
# este numero nao ha como uma box dizer se tem o conserto: /versao e o unico lugar onde a
# frota se distingue.
SERVICO = "1.7.1"

app = FastAPI(title="NoHarm Anony API", version=SERVICO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pacote: Pacote | None = None
# A blocklist que o modo `blocklist` (e o `1`) aplica: a do manifesto do pacote unida a
# `app/blocklist.txt`. Montada no startup, porque a do manifesto so existe depois do load.
BLOCKLIST: set = set()
BLOCKLIST_EXTRA_N = 0

@app.on_event("startup")
def load_model():
    global pacote, BLOCKLIST, BLOCKLIST_EXTRA_N
    print(f"Load Model ({PACOTE_DIR}, contexto={CONTEXTO}, filtros={FILTROS})", flush=True)
    classe = PacoteFrase if CONTEXTO == "frase" else Pacote
    # `carrega` confere o md5 de cada arquivo contra o manifesto: pacote montado com outro
    # `.onnx` prediz outra coisa sem nenhum sinal, e isso tem de derrubar o startup.
    pacote = classe.carrega(PACOTE_DIR, threads=THREADS)
    extra = carrega_blocklist()
    BLOCKLIST_EXTRA_N = len(extra)
    BLOCKLIST = set(pacote.blocklist) | extra
    print(f"Done! versao {pacote.versao} | blocklist: {len(pacote.blocklist)} do manifesto "
          f"+ {BLOCKLIST_EXTRA_N} extra"
          f"{'' if FILTROS_BLOCKLIST else ' (INATIVA: ANONY_FILTROS=0)'}", flush=True)
    # `preparo.plain_do_html` e copia do `to_plain` do runtime (o CI nao tem pacote para
    # importar). Se uma das duas mudar sozinha, o modelo passa a ler um texto que nenhuma
    # regua mediu — entao isso e erro de arranque, nao aviso.
    try:
        from anony_onnx_runtime import to_plain
    except ImportError:
        to_plain = None
    if to_plain is not None and to_plain(CANARIO) != plain_do_html(CANARIO):
        raise SystemExit("preparo.plain_do_html diverge do to_plain do runtime no canario")

def rtf_to_text(rtf_content, errors):
    """RTF -> HTML pelo `unrtf`, em arquivo EXCLUSIVO de cada chamada.

    Ate o servico 1.7 o arquivo era `input.rtf`, nome FIXO no diretorio de trabalho do
    processo. O `/clean` e um `def` sincrono, entao o Starlette despacha cada pedido para
    uma thread do threadpool do uvicorn (processo unico, sem `--workers`): duas chamadas
    RTF concorrentes escreviam e liam o MESMO arquivo, e o `unrtf` de uma lia o RTF que a
    outra acabara de sobrescrever.

    O desfecho e o texto de OUTRO paciente na resposta deste, com
    `fkevolucao`/`nratendimento`/`dtevolucao` corretos, ou seja PHI trocado que nada no
    destino acusa. Medido contra a 1.7 com 10 PUTs simultaneos, cada um com um marcador
    unico no corpo RTF: 9 respostas erradas — 5 com o texto de outra requisicao e 4 VAZIAS
    (o `unrtf` falha no arquivo escrito pela metade e a nota sai sem texto: a perda
    silenciosa da mesma corrida). O gatilho de producao e o
    `[Notes] Pull Oracle Data` do NiFi trazendo dezenas de evolucoes por lote para o
    `InvokeHTTP`, que abre varias conexoes — concorrencia real sempre que duas notas em RTF
    chegam juntas.

    Nome unico por chamada resolve a corrida sem serializar o `unrtf` (um lock custaria
    vazao, e a vazao aqui e o que o orcamento de `TIMEOUT_S` gasta). O `unrtf` le o arquivo
    e escreve em stdout, entao nao ha outro estado compartilhado no disco.
    """
    caminho = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".rtf", delete=False, errors=errors
        ) as rtf_file:
            caminho = rtf_file.name
            rtf_file.write(rtf_content)

        # Lista em vez de `shell=True`: o caminho vem do tempfile e nao passa por shell
        # nenhum, e uma chamada a menos de `/bin/sh` por nota.
        result = subprocess.run(
            ["unrtf", "--html", caminho], text=True, capture_output=True
        )
        if result.returncode == 0:
            return result.stdout
        print(f"Error: {result.stderr}")
        return None
    finally:
        # Sem isto o /tmp do container cresce uma nota por pedido RTF, e o que fica no disco
        # e justamente o texto em claro que este servico existe para nao deixar por ai.
        if caminho:
            try:
                os.unlink(caminho)
            except OSError:
                pass

def remove_html_tags(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()

def replace_breaklines(text):
    clean = re.compile(r"([\r?\n|\r])")
    return re.sub(clean, r". \1", text)

def plain_para_o_modelo(original_text):
    """`espaco` (1.6): tag vale espaco, igual ao runtime; `bs4` (1.5): get_text() sem separador."""
    if PLAIN == "bs4":
        return remove_html_tags(replace_breaklines(original_text))
    return plain_do_html(original_text)

def is_rtf(text):
    return "{rtf" in text[:100].replace("\\", "")

def remove_ner(spans, original_text) -> str:
    """Redacao por FORMA sobre o texto original — a decisao mora em `app/redacao.py`.

    Ate o servico 1.4 o padrao era `\b + re.escape(span) + \b` montado aqui, e ele falhava
    CALADO em duas familias: **espaco que nao e espaco** (NBSP entre as palavras do nome —
    5 de 28 spans de producao numa amostra de 170 evolucoes reais, dois deles nome de
    paciente) e **borda de pontuacao** (`Everton,`, `(  Rosangela`, que `\b` nunca casa). Nos
    dois o modelo ACHAVA o nome e a redacao o descartava, sem nada no log.

    Continua sendo por forma, com IGNORECASE, em todas as ocorrencias: o que mudou e que a
    forma deixou de depender de qual espaco o hospital digitou. Numeros e limites conhecidos
    (HTML no meio do nome segue sem casar) estao no modulo.
    """
    soup = BeautifulSoup(original_text, "html.parser")
    return redige(spans, str(soup), por_pedacos=REDACAO_PEDACOS)

def remove_accents(input_str):
    nfkd_form = unicodedata.normalize("NFKD", input_str)
    only_ascii = nfkd_form.encode("ASCII", "ignore").decode("utf-8")
    return str(only_ascii)

PRESERVE_PATTERNS = [
    re.compile(
        r"((?:comunicado|avisado)\s*(?:para\s*\(nome\)\s*:?)?\s*:?\s*(?:</b>)?\s*(?:enf[ªºao]?\.?|dr[a]?\.?)?\s*:?\s*)\*\*\*",
        re.IGNORECASE,
    ),
]

def restore_context(anonymized_text, original_text):
    result = anonymized_text
    for pattern in PRESERVE_PATTERNS:
        for match in pattern.finditer(anonymized_text):
            prefix = match.group(1)
            prefix_pattern = re.compile(
                re.escape(prefix) + r"(.+?)(?:<br\s*/?>|</?p>|</?div>|\n|$)",
                re.IGNORECASE,
            )
            original_match = prefix_pattern.search(original_text)
            if original_match:
                original_name = original_match.group(1).strip()
                if original_name and original_name != "***":
                    result = result.replace(
                        match.group(0),
                        match.group(1) + original_name,
                        1,
                    )
    return result

def achados(spans):
    """Textos dos spans que o servico vai redigir, segundo `ANONY_FILTROS`.

    `0`: TUDO que o modelo marcou — como sempre foi. `blocklist`: tudo menos a forma que
    esta na blocklist (manifesto + `app/blocklist.txt`), sem corte de confianca e sem
    exigencia de maiuscula. `1`: os filtros do runtime (confianca minima + forma de nome)
    mais a blocklist extra — redige menos termo clinico por engano e, em troca, deixa de
    redigir nome escrito todo em minuscula. Os tres sao mudanca de produto, nao de motor.
    """
    if FILTROS_RUNTIME:
        spans = [s for s in spans if s["prod"]]
    if FILTROS_BLOCKLIST:
        spans = filtra_blocklist(spans, BLOCKLIST)
    return [s["texto"] for s in spans]


@app.get("/")
def hello():
    return "Hello World from FastAPI"


@app.get("/versao")
def versao():
    """Fronteira de versao: sem isto, a resposta de antes e a de depois de uma troca de
    modelo sao indistinguiveis para quem opera o servico.

    Sao DUAS versoes, porque mudam separado: `servico` e o codigo deste repositorio e
    `pacote` e o modelo ONNX baixado no build. Uma resposta nova com o mesmo modelo — o
    caso do modo `parcial` — so aparece na primeira.

    Fora isso, so a configuracao: nome de arquivo e hash do modelo ficam de fora de
    proposito, porque identificam o artefato para qualquer um que alcance a porta, e quem
    precisa disso ja tem o `manifest.json` dentro do container.
    """
    return {
        "servico": SERVICO,
        "pacote": pacote.versao if pacote else None,
        "contexto": CONTEXTO,
        "filtros": FILTROS_RUNTIME,
        "filtros_modo": FILTROS,
        # quantas formas a blocklist aplicada tem (manifesto + extra); `null` = inativa
        "blocklist": len(BLOCKLIST) if FILTROS_BLOCKLIST else None,
        "blocklist_extra": BLOCKLIST_EXTRA_N,
        "redacao_pedacos": REDACAO_PEDACOS,
        "plain": PLAIN,
        "max_time": MAX_TIME,
        "timeout_s": TIMEOUT_S,
        "orcamento": ORCAMENTO,
        # A vazao MEDIDA nesta maquina: e o unico numero que diz o que esta instalacao
        # aguenta, e nao ha como saber de fora sem ele. `null` = ainda sem amostra.
        "vazao_chars_s": round(medidor.vazao) if medidor.vazao else None,
        "amostras": medidor.amostras,
    }

@app.put("/clean")
def get_clean_text(payload: dict = Body(...)):
    global pacote
    if pacote is None:
        return JSONResponse(
            {"status": "error", "message": "Model not loaded"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    text = payload.get("text", payload.get("TEXT", ""))
    original_text = payload.get("text", payload.get("TEXT", ""))
    format_ = payload.get("format", "html")
    preserve_context = payload.get("preserve_context", payload.get("PRESERVE_CONTEXT", []))

    try:
        # Relogio do pedido INTEIRO. O `start` mais abaixo e outro, e serve so ao guard do
        # modo `frase`. A vazao tem de incluir o preparo (unrtf, BeautifulSoup, tokenize):
        # e ela que vira estimativa, e o cliente espera pelo pedido todo, nao pela inferencia.
        t0 = time.time()
        if format_ == "rtf" or is_rtf(original_text):
            text = remove_accents(text)
            original_text = rtf_to_text(text, errors="ignore") or ""

        plain_text = plain_para_o_modelo(original_text)
        sents_words = sent_tokenize(plain_text)

        # Orcamento ANTES da inferencia: o preparo acima (rtf/html/tokenize) e barato, a
        # inferencia e que custa. Recusar aqui devolve em milissegundos o mesmo desfecho que
        # o cliente teria depois de esperar o timeout inteiro — porem dito, e sem queimar a
        # CPU da box num pedido que ninguem mais espera.
        estimativa = medidor.estimativa(len(plain_text))
        frases_lidas = sents_words
        nao_lidos = 0
        aviso = None
        # Chars que de fato vao ao modelo — e nao `len(plain_text) - nao_lidos`, que joga
        # TODO o espaco entre frases do documento para o lado lido e por isso INFLA a vazao
        # medida. Vazao inflada e orcamento maior, orcamento maior e mais texto lido: o erro
        # se realimenta. Medido antes do conserto: o mesmo prefixo de ~16 mil chars subia
        # para 18 mil conforme o texto total crescia de 43 mil para 174 mil.
        chars_inferidos = len(plain_text)
        if not cabe_no_orcamento(len(plain_text), estimativa, TIMEOUT_S):
            # `frases_que_cabem` devolve 0 quando nem a primeira frase cabe. Ali nao ha
            # redacao parcial a entregar, e um 200 com o texto INTEIRO em claro seria o
            # vazamento silencioso que o 413 existe para nao produzir — entao o piso do modo
            # `parcial` e recusar igual ao default.
            cabem = (
                frases_que_cabem(sents_words, chars_que_cabem(medidor.vazao, TIMEOUT_S))
                if PARCIAL
                else 0
            )
            if cabem == 0:
                return JSONResponse(
                    {
                        "status": "error",
                        "message": motivo_recusa(
                            len(plain_text), estimativa, TIMEOUT_S, medidor.vazao
                        ),
                        "chars": len(plain_text),
                        "estimativa_s": round(estimativa, 1),
                        "timeout_s": TIMEOUT_S,
                    },
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            # So o prefixo entra na inferencia. O que sobrou e contado pelas frases que
            # ficaram de fora, NUNCA por diferenca de `len()` contra o texto rejuntado: o
            # join normaliza espaco e faria um texto lido inteiro sair rotulado "parcial".
            frases_lidas = sents_words[:cabem]
            nao_lidos = sum(len(f) for f in sents_words[cabem:])
            chars_inferidos = sum(len(f) for f in frases_lidas)
            aviso = aviso_parcial(nao_lidos, len(plain_text), TIMEOUT_S, medidor.vazao)

        start = time.time()
        spans = []
        sent_length = 0

        if CONTEXTO == "frase":
            chars_inferidos = 0
            for s in frases_lidas:
                sent_length += len(s) / 100
                # Orcamento do modo antigo, mantido so como rollback. Ele NAO e um limite de
                # tempo: `sent_length` cresce com o TAMANHO do texto e domina o termo de
                # relogio, entao o corte cai por volta de 2.000 caracteres em qualquer
                # maquina, e acelerar o motor nao o move. Custa 31 pontos de recall — ver a
                # tabela em `CONTEXTO`, acima.
                if (time.time() - start + sent_length) < MAX_TIME:
                    spans.extend(achados(pacote.spans_do_texto(s, plain=s)))
                    chars_inferidos += len(s)
                else:
                    nao_lidos += len(s)
        else:
            # Uma chamada so, com contexto de documento — o corte do modo `parcial` e
            # ANTERIOR a inferencia, nao uma reparticao dentro dela (que e o que a secao
            # "Por que estimar, e nao interromper no meio" do orcamento recusa).
            lido = " ".join(frases_lidas) if nao_lidos else plain_text
            chars_inferidos = len(lido)
            spans = achados(pacote.spans_do_texto(lido, plain=lido))

        # Creditar o texto inteiro a um tempo que so cobriu parte dele inflaria a vazao — e
        # vazao inflada e corte que nao acontece, ou seja o orcamento deixaria de proteger
        # justamente sob carga. O relogio e o do pedido INTEIRO de proposito: e a parede que
        # o cliente ve, e nao so a inferencia.
        medidor.registra(chars_inferidos, time.time() - t0)

        # Trecho nao lido = nome nao redigido, e e por isso que o DEFAULT recusa: um 200
        # mudo com texto meio-redigido e o mecanismo exato dos 519 nomes da tabela la em
        # cima — o cliente grava e nada no monitoramento acusa. `ANONY_ORCAMENTO=parcial`
        # troca a recusa por um 200 que DIZ o que ficou por ler; o que continua nao
        # existindo e o 200 calado.
        # `aviso is None` porque o corte do prefixo (acima) ja explicou a causa certa:
        # com `frase` E `ANONY_TIMEOUT_S` os dois cortam, e a mensagem do MAX_TIME
        # sozinha mandaria mexer no knob errado.
        if nao_lidos and CONTEXTO == "frase" and aviso is None:
            aviso = (
                f"orcamento do modo frase cortou {nao_lidos} de {len(plain_text)} chars "
                f"antes de ler: o texto redigido esta INCOMPLETO. "
                f"Suba o ANONY_MAX_TIME (teto ~= valor * 100 chars) "
                f"ou use ANONY_CONTEXTO=documento, que nao tem este corte."
            )

        if nao_lidos and not PARCIAL:
            return JSONResponse(
                {
                    "status": "error",
                    "message": aviso,
                    "chars": len(plain_text),
                    "chars_nao_lidos": nao_lidos,
                    "max_time": MAX_TIME,
                },
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # A redacao e por TEXTO do span, sobre o original inteiro: nome achado no prefixo
        # lido tambem e apagado onde reaparece no trecho nao lido. Entao `chars_nao_lidos` e
        # piso de exposicao, nao medida dela — nao usar como estimativa de vazamento.
        clean_text = remove_ner(spans, original_text)

        cargo = payload.get("cargo", payload.get("CARGO", ""))
        if preserve_context and cargo in preserve_context:
            clean_text = restore_context(clean_text, original_text)

        corpo = {
            "status": "success",
            "fkevolucao": payload.get("fkevolucao", payload.get("FKEVOLUCAO", "1234")),
            "dtevolucao": payload.get("dtevolucao", payload.get("DTEVOLUCAO", "2021-01-01")),
            "cargo": payload.get("cargo", payload.get("CARGO", "cargo")),
            "prescritor": payload.get("nome", payload.get("NOME", "nome")),
            "nratendimento": payload.get("nratendimento", payload.get("NRATENDIMENTO", "1234")),
            "texto": clean_text,
            "total": len(sents_words),
        }
        if nao_lidos:
            # Campos extras SO no parcial. No caminho feliz a resposta segue identica a de
            # sempre: `put-db-record-unmatched-field-behavior` do PutDatabaseRecord pode
            # estar em "Fail on Unmatched Fields" em algum cliente, e nao se paga quebrar a
            # nota que ja funcionava para rotular a que, sem isto, estaria perdida.
            corpo["redacao"] = "parcial"
            corpo["chars_nao_lidos"] = nao_lidos
            corpo["chars_total"] = len(plain_text)
            corpo["aviso"] = aviso

        return JSONResponse(corpo, status_code=status.HTTP_200_OK)

    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e) + "".join(traceback.format_exc())},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )