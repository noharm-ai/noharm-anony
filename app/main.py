from flask import request, url_for, jsonify
from flask_api import FlaskAPI, status
from flask_cors import CORS
from striprtf.striprtf import rtf_to_text
from flair.models import SequenceTagger
from flair.data import Sentence
from nltk.tokenize import sent_tokenize
from flair.visual.ner_html import split_to_spans
import re, nltk
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

app = FlaskAPI(__name__)
CORS(app)

print('Load Punkt')
nltk.download('punkt')
print('Load Model')
tagger = SequenceTagger.load('best-model.pt')

def remove_html_tags(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

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
        line = "".join(spans_html)
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

        sents_words = sent_tokenize(plainText)

        sentences = []
        for s in sents_words:
            sentences.append(Sentence(s))

        print('Predicting...')
        tagger.predict(sentences)
        print('Predicted.')

        cleanText = remove_ner(sentences)

        return {
            'status': 'success',
            'text': text,
            'texto': cleanText
        }, status.HTTP_200_OK

    except Exception as e:

        return {
            'status': 'error',
            'message': str(e)
        }, status.HTTP_500_INTERNAL_SERVER_ERROR

if __name__ == "__main__":
    app.run(debug=True)
