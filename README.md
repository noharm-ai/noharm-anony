# Serviço Local de Remoção de Nomes

TBD

### 1. Run Docker

```
docker build -t anony . #build

docker run -p 80:80 anony #test

docker run -d --name myanony -p 80:80 anony #deamon

docker run -d --name myanony -m 2g --memory-swap="2g" --net noharm-net --ip 172.19.0.3 -p 80:80 anony #advanced

```
### 2.1 Development

```
$ python3 -m venv env
$ source env/bin/activate
$ pip3 install -r requirements.txt
```
