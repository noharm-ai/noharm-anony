import re, time, traceback, unicodedata, subprocess
from bs4 import BeautifulSoup
from flair.models import SequenceTagger
from flair.data import Sentence
from nltk.tokenize import sent_tokenize

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette import status

MAX_TIME = 20

app = FastAPI(title="NoHarm Anony API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tagger: SequenceTagger | None = None

@app.on_event("startup")
def load_model():
    global tagger
    print("Load Model", flush=True)
    tagger = SequenceTagger.load("noharm-anony-ettin-17m.pt")
    print("Done!", flush=True)

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

def remove_ner(sentences, original_text) -> str:
    soup = BeautifulSoup(original_text, "html.parser")
    replaced_text = str(soup)
    for s in sentences:
        for l in s.get_labels():
            replaced_text = re.sub(
                r"\b(" + re.escape(l.data_point.text) + r")\b",
                "***",
                replaced_text,
                flags=re.IGNORECASE,
            )
    return replaced_text

def remove_accents(input_str):
    nfkd_form = unicodedata.normalize("NFKD", input_str)
    only_ascii = nfkd_form.encode("ASCII", "ignore").decode("utf-8")
    return str(only_ascii)

@app.get("/")
def hello():
    return "Hello World from FastAPI"

@app.put("/clean")
def get_clean_text(payload: dict = Body(...)):
    global tagger
    if tagger is None:
        return JSONResponse(
            {"status": "error", "message": "Model not loaded"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    text = payload.get("text", payload.get("TEXT", ""))
    original_text = payload.get("text", payload.get("TEXT", ""))
    format_ = payload.get("format", "html")

    try:
        if format_ == "rtf" or is_rtf(original_text):
            text = remove_accents(text)
            original_text = rtf_to_text(text, errors="ignore") or ""

        plain_text = replace_breaklines(original_text)
        plain_text = remove_html_tags(plain_text)
        sents_words = sent_tokenize(plain_text)

        start = time.time()
        sentences = []
        sent_length = 0

        for s in sents_words:
            sent_length += len(s) / 100
            sent = Sentence(s)

            if (time.time() - start + sent_length) < MAX_TIME:
                tagger.predict(sent, verbose=True)
            sentences.append(sent)

        clean_text = remove_ner(sentences, original_text)

        return JSONResponse(
            {
                "status": "success",
                "fkevolucao": payload.get("fkevolucao", payload.get("FKEVOLUCAO", "1234")),
                "dtevolucao": payload.get("dtevolucao", payload.get("DTEVOLUCAO", "2021-01-01")),
                "cargo": payload.get("cargo", payload.get("CARGO", "cargo")),
                "prescritor": payload.get("nome", payload.get("NOME", "nome")),
                "nratendimento": payload.get("nratendimento", payload.get("NRATENDIMENTO", "1234")),
                "texto": clean_text,
                "total": len(sentences),
            },
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e) + "".join(traceback.format_exc())},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )