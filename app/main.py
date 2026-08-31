import os, re, sys, time, traceback, unicodedata, subprocess
from bs4 import BeautifulSoup
from nltk.tokenize import sent_tokenize

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette import status

MAX_TIME = 20

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
# Por isso o default aqui reproduz o comportamento de sempre: a troca e so de motor, e
# mudar a semantica fica sendo uma decisao separada, com medicao propria.
CONTEXTO = os.environ.get("ANONY_CONTEXTO", "frase")
FILTROS = os.environ.get("ANONY_FILTROS", "0") == "1"
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

app = FastAPI(title="NoHarm Anony API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pacote: Pacote | None = None

@app.on_event("startup")
def load_model():
    global pacote
    print(f"Load Model ({PACOTE_DIR}, contexto={CONTEXTO}, filtros={FILTROS})", flush=True)
    classe = PacoteFrase if CONTEXTO == "frase" else Pacote
    # `carrega` confere o md5 de cada arquivo contra o manifesto: pacote montado com outro
    # `.onnx` prediz outra coisa sem nenhum sinal, e isso tem de derrubar o startup.
    pacote = classe.carrega(PACOTE_DIR, threads=THREADS)
    print(f"Done! versao {pacote.versao}", flush=True)

def rtf_to_text(rtf_content, errors):
    with open("input.rtf", "w") as rtf_file:
        rtf_file.write(rtf_content)

    command = "unrtf --html input.rtf"
    result = subprocess.run(command, shell=True, text=True, capture_output=True)
    if result.returncode == 0:
        return result.stdout
    print(f"Error: {result.stderr}")
    return None

def remove_html_tags(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()

def replace_breaklines(text):
    clean = re.compile(r"([\r?\n|\r])")
    return re.sub(clean, r". \1", text)

def is_rtf(text):
    return "{rtf" in text[:100].replace("\\", "")

def remove_ner(spans, original_text) -> str:
    """Mesma redacao de sempre: `\b...\b` com IGNORECASE sobre o texto original.

    Nao foi mexido de proposito: trocar a forma da substituicao mudaria o texto entregue,
    e o que esta em jogo nesta mudanca e so o motor de inferencia.
    """
    soup = BeautifulSoup(original_text, "html.parser")
    replaced_text = str(soup)
    for span in spans:
        replaced_text = re.sub(
            r"\b(" + re.escape(span) + r")\b",
            "***",
            replaced_text,
            flags=re.IGNORECASE,
        )
    return replaced_text

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
    """Textos dos spans. Sem `ANONY_FILTROS`, TUDO que o modelo marcou — como sempre foi.

    Com `ANONY_FILTROS=1` valem os filtros do runtime (confianca minima e forma de nome):
    redige menos termo clinico por engano, e em troca deixa de redigir nome escrito todo em
    minuscula. E mudanca de produto, nao de motor.
    """
    return [s["texto"] for s in spans if s["prod"] or not FILTROS]


@app.get("/")
def hello():
    return "Hello World from FastAPI"


@app.get("/versao")
def versao():
    """Fronteira de versao: sem isto, a resposta de antes e a de depois de uma troca de
    modelo sao indistinguiveis para quem opera o servico.

    So a versao do pacote e a configuracao — nome de arquivo e hash do modelo ficam de
    fora de proposito: identificam o artefato para qualquer um que alcance a porta, e quem
    precisa disso ja tem o `manifest.json` dentro do container.
    """
    return {
        "pacote": pacote.versao if pacote else None,
        "contexto": CONTEXTO,
        "filtros": FILTROS,
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
        if format_ == "rtf" or is_rtf(original_text):
            text = remove_accents(text)
            original_text = rtf_to_text(text, errors="ignore") or ""

        plain_text = replace_breaklines(original_text)
        plain_text = remove_html_tags(plain_text)
        sents_words = sent_tokenize(plain_text)

        start = time.time()
        spans = []
        sent_length = 0

        if CONTEXTO == "frase":
            for s in sents_words:
                sent_length += len(s) / 100
                # Orcamento: frase que nao cabe NAO e predita, e sai sem redigir. Note que
                # `sent_length` cresce com o TAMANHO do texto, entao na pratica o corte cai
                # por volta de 2.000 caracteres mesmo em maquina rapida. Com o motor ONNX
                # o corte morde mais tarde, e o texto longo passa a ser mais coberto.
                if (time.time() - start + sent_length) < MAX_TIME:
                    spans.extend(achados(pacote.spans_do_texto(s, plain=s)))
        else:
            spans = achados(pacote.spans_do_texto(plain_text, plain=plain_text))

        clean_text = remove_ner(spans, original_text)

        cargo = payload.get("cargo", payload.get("CARGO", ""))
        if preserve_context and cargo in preserve_context:
            clean_text = restore_context(clean_text, original_text)

        return JSONResponse(
            {
                "status": "success",
                "fkevolucao": payload.get("fkevolucao", payload.get("FKEVOLUCAO", "1234")),
                "dtevolucao": payload.get("dtevolucao", payload.get("DTEVOLUCAO", "2021-01-01")),
                "cargo": payload.get("cargo", payload.get("CARGO", "cargo")),
                "prescritor": payload.get("nome", payload.get("NOME", "nome")),
                "nratendimento": payload.get("nratendimento", payload.get("NRATENDIMENTO", "1234")),
                "texto": clean_text,
                "total": len(sents_words),
            },
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e) + "".join(traceback.format_exc())},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )