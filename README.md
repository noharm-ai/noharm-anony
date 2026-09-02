# Serviço Local de Remoção de Nomes

Serviço que anonimiza nomes pessoais oriundos de evoluções dos diversos profissionais (médicos, enfermeiros, farmacêuticas, etc.), substituindo os nomes por \*\*\*.

### 1. Run Docker

```
git clone https://github.com/noharm-ai/noharm-anony

cd noharm-anony

docker build -t anony . #build

docker run -p 80:80 anony #test

docker run -d --log-opt max-size=100m --name myanony -p 80:80 anony #deamon
```

### 1.1. Identificar o IP e alterar no Remote URL do Nifi (no InvokeHTTP)

```
docker network inspect bridge
```

### 1.2. Testar Plain

```
curl -X PUT -H 'Accept: application/json' -H 'Content-Type: application/json' http://localhost/clean -d '{"text" : "FISIOTERAPIA TRAUMATO - MANHÃ  Henrique Dias, 38 anos. Exercícios metabólicos de extremidades inferiores. Realizo mobilização patelar e leve mobilização de flexão de joelho conforme liberado pelo Dr Marcelo Arocha. Oriento cuidados e posicionamentos."}'
```

### 1.2. Testar RTF

```
curl -X PUT -H 'Accept: application/json' -H 'Content-Type: application/json' http://localhost/clean -d '{"text" : "{\\rtf1\\ansi\\b FISIOTERAPIA TRAUMATO - MANHÃ  Henrique Dias, 38 anos.\\b0.\\par \\i Exercícios metabólicos de extremidades inferiores. Realizo mobilização patelar e leve mobilização de flexão de joelho conforme liberado pelo Dr Marcelo Arocha. Oriento cuidados e posicionamentos.\\i0.}"}'
```

### 2. Outras configurações

### 2.1. Run Network Docker

```
docker network create --subnet=172.19.0.0/16 noharm-net

docker network connect noharm-net nifi

docker run -d --log-opt max-size=100m --name myanony --net noharm-net --ip 172.19.0.3 -p 80:80 anony
```

### 2.2. Run Limited Memory Docker

```
docker run -d --name myanony -m 2g --memory-swap="2g" -p 80:80 anony
```

### 2.3 RTF Format

RTF should be detected automatically but you can force the input to be handled as a RTF using the FORMAT parameter. Example:

```
curl -X PUT -H 'Accept: application/json' -H 'Content-Type: application/json' http://localhost/clean -d '{"format": "rtf", "text" : "FISIOTERAPIA TRAUMATO - MANHÃ  Henrique Dias, 38 anos. Exercícios metabólicos de extremidades inferiores. Realizo mobilização patelar e leve mobilização de flexão de joelho conforme liberado pelo Dr Marcelo Arocha. Oriento cuidados e posicionamentos."}'
```

### 2.4 Tempo de resposta e o timeout do cliente

O `InvokeHTTP` do NiFi que chama este serviço tem **Read Timeout** próprio (15 s na frota).
Quando o `/clean` demora mais que isso o cliente desiste, o flowfile é descartado — e o
serviço **continua processando** um pedido que ninguém espera. Como o reprocessamento
manda a mesma nota de volta, vira laço: CPU queimada, nota nunca escrita.

Quanto tempo uma nota leva depende da máquina, e a frota vai de Xeon E5420 (2007) a Xeon
Silver 4514Y. Medido com a mesma carga:

| texto | Xeon Silver | Xeon E5420 |
|---|---|---|
| ~1.000 chars | — | 1,4 s |
| ~6.000 chars | — | 9,7 s |
| ~8.000 chars | 1,6 s | **24,5 s** |
| 76.000 chars | 13,0 s | — |

`ANONY_TIMEOUT_S` resolve isso sem calibração por box: o serviço **mede a própria vazão**
(caracteres por segundo, visível em `/versao`) e, em milissegundos e com o motivo dito,
decide o que fazer com o texto que não caberia no orçamento — por padrão, recusa.

```
docker run -d --name myanony -e ANONY_TIMEOUT_S=12 -p 80:80 anony
```

Ajuste-o **abaixo** do Read Timeout do cliente — o orçamento cobre a inferência, e rede e
serialização ainda vêm por cima. Sem a variável (default `0`) nada é recusado, que é o
comportamento anterior. A recusa sai como **HTTP 413** com `chars`, `estimativa_s` e
`timeout_s` no corpo.

Enquanto não houver nenhuma amostra medida, nada é recusado: a primeira nota longa depois
do boot passa e é ela que ensina a vazão à instalação.

### 2.4.1 Recusar ou redigir só o que cabe (`ANONY_ORCAMENTO`)

Recusar entrega o desfecho certo para o **paciente** — nada meio-redigido é gravado — e o
errado para o **dado**: a nota não existe. Onde o cliente não consegue reprocessar (flow que
auto-termina o `Failure`, cursor que não volta), isso é perda definitiva de evolução
clínica. Medido em 02/09/2026 numa box de hospital: **175 notas descartadas em 26 h**, todas
as longas, sem fila para inspecionar.

`ANONY_ORCAMENTO=parcial` dá a outra escolha:

```
docker run -d --name myanony -e ANONY_TIMEOUT_S=12 -e ANONY_ORCAMENTO=parcial -p 80:80 anony
```

Ele lê o **prefixo que cabe**, redige esse prefixo e devolve o resto como no original, com
**200** e com o quanto ficou por ler dito na resposta:

```json
{"status": "success", "fkevolucao": 42, "texto": "...", "total": 812,
 "redacao": "parcial", "chars_nao_lidos": 65878, "chars_total": 78657,
 "aviso": "redacao PARCIAL: os 65878 chars finais de 78657 nao foram lidos e ..."}
```

Três coisas que ele **não** é:

- **Não é o modo `frase` de volta.** O corte é medido (`vazão × ANONY_TIMEOUT_S`, o inverso
  exato da recusa), não os ~2.000 chars fixos do `ANONY_MAX_TIME`, e o prefixo vai ao
  modelo numa chamada só, com contexto de documento. Pelos números da avaliação, dos 548
  nomes que o modo `frase` deixa em claro **519 estão em trecho nunca lido** e só 29 são
  erro de modelo: o custo de recall é de não ler, não de fragmentar.
- **Não é silencioso.** Os campos `redacao`, `chars_nao_lidos`, `chars_total` e `aviso`
  aparecem **só** quando houve corte — no caminho feliz a resposta é idêntica à de sempre,
  para não quebrar cliente com `Fail on Unmatched Fields` no `PutDatabaseRecord`.
- **Não devolve texto inteiro em claro.** Se nem a primeira frase cabe, ele **recusa** como
  o default: zero redação não é redação parcial, e nenhum rótulo tornaria isso aceitável.

⚠️ `chars_nao_lidos` é **piso** de exposição, não medida dela: a redação é pelo texto do
span sobre o original inteiro, então nome achado no prefixo também é apagado onde reaparece
na cauda.

### 2.5 Variáveis de ambiente

| variável | default | o que faz |
|---|---|---|
| `ANONY_CONTEXTO` | `documento` | `frase` volta ao modo antigo (predição por sentença isolada). Custa 31 pontos de recall — ver o comentário em `app/main.py`. |
| `ANONY_TIMEOUT_S` | `0` (desligado) | Orçamento de tempo por requisição, em segundos. Ver 2.4. |
| `ANONY_ORCAMENTO` | `recusa` | O que fazer com o texto que não cabe. `parcial` redige o prefixo que cabe e devolve o resto como original, com 200 rotulado. Ver 2.4.1. |
| `ANONY_MAX_TIME` | `20` | Teto do modo `frase`. **O nome diz tempo e o efeito é tamanho**: o corte cai por volta de `valor × 100` caracteres. Só tem efeito com `ANONY_CONTEXTO=frase`. |
| `ANONY_FILTROS` | `0` | `1` aplica os filtros de confiança e forma de nome do runtime. |
| `ANONY_THREADS` | `0` (todas) | Threads do onnxruntime. |
| `ANONY_PACOTE_DIR` | `/app/noharm-anony-onnx` | Onde o pacote do modelo foi extraído. |

No modo `frase`, se o teto cortar antes de ler o texto inteiro a resposta é **413**, não um
200 com o texto meio-redigido: trecho não lido é nome não redigido, e o cliente gravaria o
vazamento sem nada acusar. Com `ANONY_ORCAMENTO=parcial` ela vira um 200 **rotulado**
(`redacao: "parcial"`) — o que continua não existindo é o 200 calado.

### 2.6 Development

```
$ python3 -m venv env
$ source env/bin/activate
$ pip3 install -r requirements.txt
```
