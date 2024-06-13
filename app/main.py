from flask import request
from flask_api import FlaskAPI, status
from flask_cors import CORS
import subprocess
from flair.models import SequenceTagger
from flair.data import Sentence
from nltk.tokenize import sent_tokenize
from waitress import serve
from bs4 import BeautifulSoup
import re, time, traceback, unicodedata

print('Load Model', flush=True)
tagger = SequenceTagger.load('final-model.pt')
print('Done!', flush=True)

def create_app():
    app = FlaskAPI(__name__)
    CORS(app)

    return app

app = create_app()

def rtf_to_text(rtf_content, errors):

    with open("input.rtf", "w") as rtf_file:
        rtf_file.write(rtf_content)    

    command = f'unrtf --html input.rtf'

    try:
        # Run the command and capture the output
        result = subprocess.run(command, shell=True, text=True, capture_output=True)

        # Check if the command was successful
        if result.returncode == 0:
            return result.stdout
        else:
            # Print the error message if the command failed
            print(f"Error: {result.stderr}")
            return None

    except Exception as e:
        print(f"An error occurred: {e}")
        return None


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
            replaced_text = re.sub(r"\b(" + l.data_point.text + r")\b", '***', replaced_text, flags=re.IGNORECASE)
    
    return replaced_text

def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    only_ascii = nfkd_form.encode('ASCII', 'ignore')
    only_ascii = only_ascii.decode('utf-8')
    return str(only_ascii)

@app.route("/")
def hello():
    return "Hello World from Flask"

@app.route("/clean", methods=['PUT'])
def getCleanText():
    data = request.get_json()
    text = data.get('text', data.get('TEXT', ''))
    original_text = data.get('text', data.get('TEXT', ''))
    format = data.get('format', 'html')
    cleanText = ''

    try:

        if format == 'rtf' or is_rtf(original_text):
            text = remove_accents(text)
            original_text = rtf_to_text(text, errors="ignore")            

        plainText = replace_breaklines(original_text)
        plainText = remove_html_tags(plainText)
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
            'fkevolucao': data.get('fkevolucao', data.get('FKEVOLUCAO', '1234')),
            'dtevolucao': data.get('dtevolucao', data.get('DTEVOLUCAO', '2021-01-01')),
            'cargo': data.get('cargo', data.get('CARGO', 'cargo')),
            'prescritor': data.get('nome', data.get('NOME', 'nome')),
            'nratendimento': data.get('nratendimento', data.get('NRATENDIMENTO', '1234')),
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
