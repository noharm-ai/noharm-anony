FROM python:3.8-slim-buster

RUN apt-get update && apt-get install -y wget

ENV FLASK_APP=anonyapp
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=80

WORKDIR /app

COPY requirements.txt /app
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

RUN wget -c https://noharm.ai/anony/best-model.pt -P /app --no-check-certificate

COPY ./app/ /app

EXPOSE 80
ENV PORT 80

CMD python main.py