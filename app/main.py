from flask import request, url_for, jsonify
from flask_api import FlaskAPI, status
from flask_cors import CORS
from striprtf.striprtf import rtf_to_text
from flair.models import SequenceTagger
from flair.data import Sentence
from nltk.tokenize import sent_tokenize
from flair.visual.ner_html import split_to_spans
from waitress import serve
import re, nltk
import ssl, time

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

print('Load Punkt')
nltk.download('punkt')
print('Load Model')
tagger = SequenceTagger.load('best-model.pt')

def create_app():
    app = FlaskAPI(__name__)
    CORS(app)

    return app

app = create_app()

def remove_html_tags(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

PARAGRAPH = """<p>{sentence}</p>"""
MAX_TIME = 20

def remove_ner(sentences) -> str:
    sentences_html = []
    for s in sentences:
        spans = split_to_spans(s)
        spans_html = list()
        for fragment, tag in spans:
            escaped_fragment = fragment
            if tag:
                escaped_fragment = '***'
            spans_html.append(escaped_fragment)
        line = PARAGRAPH.format(sentence="".join(spans_html))
        sentences_html.append(line)

    return "\n".join(sentences_html)

@app.route("/")
def hello():
    return "Hello World from Flask"

@app.route("/clean", methods=['PUT'])
def getCleanText():
    data = request.get_json()
    text = data.get('TEXT', '')
    cleanText = ''

    try:

        if 'html5' in text:
            plainText = remove_html_tags(text)
        else:
            plainText = rtf_to_text(text)

        sents_words = sent_tokenize(plainText.replace('\n','.\n'))

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

        cleanText = remove_ner(sentences)

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
            'message': str(e)
        }, status.HTTP_500_INTERNAL_SERVER_ERROR

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=80)
