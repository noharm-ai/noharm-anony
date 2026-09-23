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
{"servico":"1.7.1","pacote":"o1.3","contexto":"documento","filtros":false,
 "filtros_modo":"blocklist","blocklist":130,"blocklist_extra":38,
 "redacao_pedacos":true,"plain":"espaco",
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
| `ANONY_PLAIN` | `espaco` | Como o HTML vira o texto que o modelo lê. `espaco` troca cada tag por um espaço, igual ao runtime do pacote e ao job do servidor. `bs4` volta ao `get_text()` sem separador da 1.5, que **funde** o fim de um `<p>` no nome seguinte e deixava 84–89% dos nomes achados sem redação em dois hospitais. Ver 2.7. |
| `ANONY_FILTROS` | `blocklist` | Deixa de redigir só a forma que está na blocklist (a do pacote unida a `app/blocklist.txt`), sem corte de confiança e sem exigência de maiúscula. `0` volta ao comportamento da 1.6: redige tudo que o modelo marca. `1` aplica também os filtros de confiança e forma de nome do runtime, e com isso deixa de redigir nome escrito todo em minúscula. Ver 2.8. |
| `ANONY_THREADS` | `0` (todas) | Threads do onnxruntime. |
| `ANONY_PACOTE_DIR` | `/app/noharm-anony-onnx` | Onde o pacote do modelo foi extraído. |

No modo `frase`, se o teto cortar antes de ler o texto inteiro a resposta é **413**, não um
200 com o texto meio-redigido: trecho não lido é nome não redigido, e o cliente gravaria o
vazamento sem nada acusar. Com `ANONY_ORCAMENTO=parcial` ela vira um 200 **rotulado**
(`redacao: "parcial"`) — o que continua não existindo é o 200 calado.

### 2.7 O texto que o modelo lê (`ANONY_PLAIN`, serviço 1.6)

Até a 1.5 o HTML virava texto por `soup.get_text()` **sem separador**. Isso apaga a fronteira
entre dois elementos: `<p>ENFERMAGEM</p><p>Fulana Beltrano, 74 anos</p>` chega ao modelo como
`ENFERMAGEMFulana Beltrano, 74 anos`. O modelo ainda marca o nome, mas emite uma forma que não
existe no HTML e a redação, que casa por forma sobre o original, não encontra nada. Quando o
sobrenome sai como span separado ele é redigido e o primeiro nome colado sobrevive — o
`Fulana ***, 74 anos` visto em dois hospitais com o pacote mais novo instalado.

Os nomes próprios dos exemplos desta seção e dos testes são **inventados** — do caso real
se preserva só a *forma* do defeito (onde a tag cai, onde o nome funde, onde entra o NBSP),
que é o que a régua mede.

Medido em 16/09/2026 sobre textos do dia, pacote o1.3, reproduzindo o `/clean` da 1.4 e da
1.5 fora do hospital:

| hospital | spans que o modelo acha | a 1.4 não redigia | por fusão de tag | a 1.5 recupera |
|---|---|---|---|---|
| A (180 textos) | 45 | 38 (84%) | 30 | 37 |
| B (158 textos) | 37 | 33 (89%) | 28 | 32 |

A 1.5 recupera quase tudo pelo fallback por pedaços, mas só o que ainda existe como palavra
inteira: `ENFERMAGEMFulana` e `Fulano8a` não se decompõem. A 1.6 conserta na origem: cada tag
vale um espaço, que é exatamente o `to_plain` do runtime do pacote e do job que redige a mesma
coluna no servidor — o texto sobre o qual toda régua desta linha foi medida. O `get_text()` era
o único caminho que o modelo via e ninguém media. Junto vem um conserto menor: o
`replace_breaklines` antigo usava a classe `[\r?\n|\r]`, que também trocava `?` e `|` por
`. ?` e `. |`.

`ANONY_PLAIN=bs4` volta ao comportamento da 1.5 sem rebuild; o modo em uso sai no `/versao`.
O serviço confere no arranque que a cópia local e o `to_plain` do runtime coincidem num
canário, e recusa subir se divergirem.

### 2.8 A blocklist e o modo `blocklist` (serviço 1.7)

Por default o serviço redige **tudo** que o modelo marca. O pacote traz uma blocklist no
`manifest.json` — a do job que redige a mesma coluna no servidor —, mas ela só agia com
`ANONY_FILTROS=1`, que liga junto o corte de confiança e a exigência de maiúscula no span; o
segundo custa recall (nome escrito todo em minúscula deixa de ser redigido), e por isso
ninguém ligava.

`ANONY_FILTROS=blocklist` separa as duas coisas: deixa de redigir **só** a forma cuja string
inteira, em `casefold`, está na blocklist — a do manifesto unida a **`app/blocklist.txt`**,
versionada neste repositório —, e continua redigindo todo o resto. Não é substring:
`higiene` na lista não toca em `Higienópolis`.

**De onde vem a lista.** Régua de produção de 17/09/2026: janela virgem, 1.976 spans
arbitrados em cego. Nenhuma forma do arquivo foi arbitrada como nome ali, nem na janela
independente de 04–10/08 medida depois; juntas cobrem **40% do falso positivo visível** do
modelo em produção naquela janela — rótulo de campo de
formulário (`Higiene Oral: : Sim`, `Eficacia`), escala clínica com epônimo, fármaco,
material, parentesco, cortesia. São as mesmas formas que entraram na blocklist do job do
servidor no mesmo dia.

**O que pode estar no arquivo, porque este repositório é público:** forma de não-nome
medida em produção. **O que não pode:** nada com leitura de nome de pessoa real, nem nome
de hospital, cidade ou paciente — isso fica na lista do job, no servidor.
`app/test_blocklist.py` segura as violações mais fáceis de cometer sem querer.

Contra as 8.029 labels do corpus de treino há **uma** colisão, inspecionada: `Sobrinha`
aparece rotulada como nome uma vez, em `Sobrinha *** informa que…`, onde o `***` é o nome já
redigido e o rótulo pegou o termo de parentesco anterior a ele — erro de anotação do gold,
não nome. A primeira contagem publicada dizia zero e estava errada: o script lia `labels` e a
chave do corpus é `label`, e nome de campo errado devolve lista vazia sem acusar nada.

O modo em uso e o tamanho da lista aplicada saem no `/versao` (`filtros_modo`, `blocklist`,
`blocklist_extra`). **`blocklist` é o default desde a 1.7.** `ANONY_FILTROS=0` volta ao
comportamento da 1.6 sem rebuild — redigir tudo que o modelo marca.

### 2.9 RTF concorrente: o texto de outro paciente (serviço 1.7.1)

Até a 1.7 a conversão RTF→HTML escrevia o corpo do pedido num arquivo de **nome fixo**
(`input.rtf`, no diretório de trabalho do processo) e chamava o `unrtf` sobre ele. O
`/clean` é um `def` síncrono, então cada pedido roda numa thread do threadpool do uvicorn
(processo único, sem `--workers`): **duas notas em RTF chegando juntas escreviam e liam o
mesmo arquivo**, e o `unrtf` de uma lia o RTF que a outra acabara de sobrescrever.

O desfecho não era erro nem nota vazia — era a evolução gravada com `fkevolucao`,
`nratendimento`, `dtevolucao` e autor **corretos** e o texto livre de **outro paciente**.
Nada no destino acusa isso: o registro existe e parece íntegro.

Medido contra a 1.7 com 10 `PUT /clean` simultâneos, cada um com um marcador único dentro
do corpo RTF: **9 das 10 respostas erradas** — 5 com o texto de *outra* requisição e 4
**vazias** (o `unrtf` falha no arquivo escrito pela metade, e o serviço devolve a nota sem
texto, que é a perda silenciosa da mesma corrida). A proporção varia com a máquina e com o
tamanho da nota; o que não varia é haver troca.

**Quem chega a ter dois pedidos em voo.** A corrida precisa disso, e a fila do NiFi *não* a
produz sozinha: um `InvokeHTTP` com `Concurrent Tasks = 1` serializa os pedidos, e um lote
de dezenas de notas só mantém a fila cheia. Medido em 21/09/2026 nos backups de flow das
instalações (205 lidos, 193 com o processador do `/clean` em `RUNNING`, 12 sem backup
legível), duas configurações abrem a corrida — e **8 instalações estão numa delas**:

| configuração | instalações | por que concorre |
|---|---|---|
| `Concurrent Tasks = 2` no `InvokeHTTP` do `/clean` | 1 | o NiFi mantém duas threads do mesmo processador, cada uma com o seu PUT |
| dois ou mais `InvokeHTTP` do `/clean` apontando para o MESMO anony | 7 | cada um é sequencial, mas eles rodam em paralelo entre si (vistos 2, 3 e 4 rodando juntos) |

⚠️ `Max Idle Connections` (5 no default do `InvokeHTTP`) **não** é paralelismo: é o pool de
conexões ociosas do cliente HTTP. Com um processador e `Concurrent Tasks = 1` ele nunca
produz dois pedidos ao mesmo tempo.

Nas demais instalações a corrida não acontecia — mas o arquivo de nome fixo deixava a
**última nota em claro no disco** do container (`/app/input.rtf`, confirmado num container
da 1.7 depois de um pedido RTF), e isso valia para todas.

A 1.7.1 dá a cada chamada um arquivo temporário exclusivo, apagado no `finally` — sem lock,
porque serializar o `unrtf` custaria vazão, e vazão é exatamente o que o orçamento de
`ANONY_TIMEOUT_S` gasta. O conserto é no serviço, e não em configuração de cliente: nada no
`/clean` dependia de o chamador ser sequencial, e nada devia depender.

Para conferir num serviço já rodando (o teste não usa PHI — os marcadores são sintéticos):

```
python3 app/test_rtf_concorrente.py http://localhost
```

### 2.6 Development

```
$ python3 -m venv env
$ source env/bin/activate
$ pip3 install -r requirements.txt
```
