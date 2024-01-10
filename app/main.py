from flask import request
from flask_api import FlaskAPI, status
from flask_cors import CORS
from striprtf.striprtf import rtf_to_text
from flair.models import SequenceTagger
from flair.data import Sentence
from nltk.tokenize import sent_tokenize
from waitress import serve
from bs4 import BeautifulSoup
import re, time, traceback


print('Load Model', flush=True)
tagger = SequenceTagger.load('best-model.pt')
print('Done!', flush=True)

def create_app():
    app = FlaskAPI(__name__)
    CORS(app)

    return app

app = create_app()

def remove_html_tags(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text()

def replace_breaklines(text):
    clean = re.compile('([\r?\n|\r])')
    return re.sub(clean, r". \1", text)

def is_rtf(text):
    if '{rtf' in text[:100].replace('\\', ''):
        return True
    
    return False

MAX_TIME = 20

def remove_ner(sentences, original_text) -> str:
    soup = BeautifulSoup(original_text, "html.parser")
    replaced_text = str(soup)

    for s in sentences:
        for l in s.get_labels():
            replaced_text = replaced_text.replace(l.data_point.text, '***')
    
    return replaced_text

@app.route("/")
def hello():
    return "Hello World from Flask"

@app.route("/clean", methods=['PUT'])
def getCleanText():
    data = request.get_json()
    text = data.get('TEXT', '')
    original_text = data.get('TEXT', '')
    format = data.get('FORMAT', 'html')
    cleanText = ''

    try:
        text = replace_breaklines(text)

        if format == 'rtf' or is_rtf(original_text):
            plainText = rtf_to_text(text, errors="ignore")
            #rtf must be replaced by plain text
            original_text = plainText
        else:
            plainText = remove_html_tags(text)

        sents_words = sent_tokenize(plainText)

        start = time.time()
        sentences = []
        sent_length = 0
        processed = 0
        for s in sents_words:
            sent_length += len(s) / 100
            sent = Sentence(s)

            end = time.time()
            if (end - start + sent_length) < MAX_TIME:
                tagger.predict(sent, verbose=True)
                sentences.append(sent)
                processed += 1
            else:
                sentences.append(sent)

        cleanText = remove_ner(sentences, original_text)

        return {
            'status': 'success',
            'fkevolucao': data.get('FKEVOLUCAO', '1234'),
            'dtevolucao': data.get('DTEVOLUCAO', '2021-01-01'),
            'cargo': data.get('CARGO', 'cargo'),
            'prescritor': data.get('NOME', 'nome'),
            'nratendimento': data.get('NRATENDIMENTO', '1234'),
            'texto': cleanText,
            'total': len(sentences)
        }, status.HTTP_200_OK

    except Exception as e:

        return {
            'status': 'error',
            'message': str(e) +  ''.join(traceback.format_exc())
        }, status.HTTP_500_INTERNAL_SERVER_ERROR

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=80)
