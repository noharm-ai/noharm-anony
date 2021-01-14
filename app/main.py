from flask import request, url_for, jsonify
from flask_api import FlaskAPI, status
from flask_cors import CORS
from striprtf.striprtf import rtf_to_text
import re

app = FlaskAPI(__name__)
CORS(app)

def remove_html_tags(text):
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

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
            cleanText = remove_html_tags(text)
        else:
            cleanText = rtf_to_text(text)

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
