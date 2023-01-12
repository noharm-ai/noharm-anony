FROM python:3.8-slim-buster

RUN apt-get update && apt-get install -y wget git vim curl htop unzip

ENV FLASK_APP=anonyapp
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=80

WORKDIR /app

COPY requirements.txt /app
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

RUN pip install conllu==4.4.2 torch==1.11.0
RUN pip install git+https://github.com/flairNLP/flair.git@726c870eb3423644e76be2ccd2815781b1fe624a

RUN wget -c https://noharm.ai/anony/best-model.pt -P /app --no-check-certificate
RUN wget -c https://noharm.ai/anony/punkt.zip -P /root/nltk_data/tokenizers/ --no-check-certificate
RUN unzip /root/nltk_data/tokenizers/punkt.zip -d /root/nltk_data/tokenizers/

COPY ./app/ /app

EXPOSE 80
ENV PORT 80

CMD python main.py
