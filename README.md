# Serviço Local de Remoção de Nomes

TBD

### 1. Run Docker

```
docker build -t anony . #build

docker run -p 80:80 anony #test

docker run -d --name myanony -p 80:80 anony #deamon
```
### 2.1 Development

```
$ python3 -m venv env
$ source env/bin/activate
$ pip3 install -r requirements.txt
```
