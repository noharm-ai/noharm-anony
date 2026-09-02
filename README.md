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

**Vem ligado, em 13 s** — como o `ANONY_MAX_TIME`, é um default e não um opt-in. 13 e não
15 porque o orçamento cobre a inferência, e rede e serialização ainda vêm por cima; ajuste-o
junto com o Read Timeout do cliente e sempre **abaixo** dele. `ANONY_TIMEOUT_S=0` desliga,
para quem chama o `/clean` de outro lugar.

Enquanto não houver nenhuma amostra medida, nada é cortado: a primeira nota longa depois do
boot passa inteira e é ela que ensina a vazão à instalação. ⚠️ O preço é que essa primeira
nota pode estourar o cliente — é o buraco que só um teto de relógio fecharia.

⚠️ **O orçamento modela a inferência do prefixo, não o pedido inteiro.** Preparo do texto,
`remove_ner` e serialização crescem com o texto **total** e nenhum corte de prefixo os evita.
Medido numa máquina de ~1.150 chars/s com `ANONY_TIMEOUT_S=13`: 13,8 s de parede em 41 mil
chars, 14,2 s em 82 mil, 14,6 s em 161 mil e **16,2 s em 320 mil**. Contra um Read Timeout de
15 s, 13 s seguram até a casa dos 150 mil chars de texto total; acima disso a nota se perde
como se perdia antes — só que em ~15 s em vez de horas, e com a vazão medida caindo, o que
aperta o orçamento sozinho.

### 2.4.1 Recusar ou redigir só o que cabe (`ANONY_ORCAMENTO`)

Recusar entrega o desfecho certo para o **paciente** — nada meio-redigido é gravado — e o
errado para o **dado**: a nota não existe. Onde o cliente não consegue reprocessar (flow que
auto-termina o `Failure`, cursor que não volta), isso é perda definitiva de evolução
clínica. Medido em 02/09/2026 numa box de hospital: **175 notas descartadas em 26 h**, todas
as longas, sem fila para inspecionar.

Por isso o default é **`parcial`**. `ANONY_ORCAMENTO=recusa` volta ao 413 com nada
processado, para quem prefere não gravar nota meio redigida e **consegue** reprocessar a
recusada:

```
docker run -d --name myanony -e ANONY_ORCAMENTO=recusa -p 80:80 anony
```

O parcial lê o **prefixo que cabe**, redige esse prefixo e devolve o resto como no original, com
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
- **Não devolve texto inteiro em claro.** Se nem a primeira frase cabe, ele **recusa** com
  413: zero redação não é redação parcial, e nenhum rótulo tornaria isso aceitável. Medido
  num cliente de notas longas (833 notas acima do orçamento numa semana), a primeira frase
  tem mediana de 164 chars e máximo de 1.582 — o piso não chegou a disparar.

⚠️ A troca do parcial é **perda silenciosa por redação parcial declarada**, não redação
completa por parcial. Mas há uma faixa em que ela é no outro sentido: nota cuja inferência
levaria entre o `ANONY_TIMEOUT_S` e o Read Timeout do cliente (13 s e 15 s nos defaults)
hoje é escrita inteira redigida e passa a sair parcial. Quem não aceita isso põe
`ANONY_ORCAMENTO=recusa`, ou sobe os dois tetos juntos.

⚠️ `chars_nao_lidos` é **piso** de exposição, não medida dela: a redação é pelo texto do
span sobre o original inteiro, então nome achado no prefixo também é apagado onde reaparece
na cauda.

### 2.4.2 `/versao`: duas versões, porque mudam separado

```
$ curl -s http://localhost/versao
{"servico":"1.4","pacote":"o1.3","contexto":"documento","filtros":false,
 "max_time":20.0,"timeout_s":13.0,"orcamento":"parcial",
 "vazao_chars_s":983,"amostras":2406}
```

`servico` é o código deste repositório; `pacote` é o modelo ONNX baixado no build
(`ARG ANONY_PACOTE`). Uma resposta nova com o mesmo modelo — o caso do modo `parcial` — só
aparece na primeira. `vazao_chars_s` é a vazão **medida nesta máquina**, e é o único número
que diz o que a instalação aguenta (`null` = ainda sem amostra).

### 2.5 Variáveis de ambiente

| variável | default | o que faz |
|---|---|---|
| `ANONY_CONTEXTO` | `documento` | `frase` volta ao modo antigo (predição por sentença isolada). Custa 31 pontos de recall — ver o comentário em `app/main.py`. |
| `ANONY_TIMEOUT_S` | `13` | Orçamento de tempo por requisição, em segundos. `0` desliga. Ver 2.4. |
| `ANONY_ORCAMENTO` | `parcial` | O que fazer com o texto que não cabe: redige o prefixo que cabe e devolve o resto como original, com 200 rotulado. `recusa` volta ao 413. Ver 2.4.1. |
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
