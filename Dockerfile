FROM python:3.13.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV NLTK_DATA=/usr/local/share/nltk_data

RUN apt-get update \
 && apt-get install -y --no-install-recommends wget unzip unrtf \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app

RUN pip install --upgrade pip \
 && pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r /app/requirements.txt

RUN wget -c https://noharm.ai/anony/noharm-anony-ettin-17m.pt -P /app --no-check-certificate 

RUN python -m nltk.downloader -d /usr/local/share/nltk_data punkt_tab

COPY ./app/ /app

EXPOSE 80

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]