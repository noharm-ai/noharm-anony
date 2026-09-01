FROM python:3.13.11-slim

# Pacote do modelo, com VERSÃO no nome. Trocar de modelo é trocar este ARG
# (`docker build --build-arg ANONY_PACOTE=noharm-anony-onnx-o1.4 .`); a versão também fica
# registrada no manifesto dentro do pacote e sai no endpoint /versao. O `.pt` antigo
# continua publicado, então o rollback é o Dockerfile anterior.
ARG ANONY_PACOTE=noharm-anony-onnx-o1.3
# Espelho local ou ambiente sem saída para a internet: aponte para outro servidor.
ARG ANONY_BASE_URL=https://noharm.ai/anony

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENV NLTK_DATA=/usr/local/share/nltk_data
ENV ANONY_PACOTE_DIR=/app/noharm-anony-onnx

RUN apt-get update \
 && apt-get install -y --no-install-recommends wget unzip unrtf \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app

# Sem torch e sem flair: o modelo agora é ONNX e roda com onnxruntime + tokenizers.
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt

# md5 conferido no build: o hash vem publicado ao lado do pacote (o ETag do S3/CloudFront é
# multipart e não é o md5 do arquivo). Download corrompido tem de derrubar o build, e não
# virar serviço que prediz errado.
RUN wget -c ${ANONY_BASE_URL}/${ANONY_PACOTE}.tar.gz -P /tmp --no-check-certificate \
 && wget -c ${ANONY_BASE_URL}/${ANONY_PACOTE}.tar.gz.md5 -P /tmp --no-check-certificate \
 && echo "$(cat /tmp/${ANONY_PACOTE}.tar.gz.md5)  /tmp/${ANONY_PACOTE}.tar.gz" | md5sum -c - \
 && tar xzf /tmp/${ANONY_PACOTE}.tar.gz -C /app \
 && rm /tmp/${ANONY_PACOTE}.tar.gz /tmp/${ANONY_PACOTE}.tar.gz.md5

RUN python -m nltk.downloader -d /usr/local/share/nltk_data punkt_tab

COPY ./app/ /app

EXPOSE 80

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
