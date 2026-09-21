"""O texto de um paciente na resposta de outro: a corrida do RTF (servico 1.7.1).

Teste de PONTA A PONTA, contra um `/clean` de verdade — ele nao importa `main.py` (que
precisa do pacote ONNX) e por isso pode rodar tanto no CI, contra o container do build,
quanto numa box de hospital para conferir se ela ja tem o conserto:

    python3 app/test_rtf_concorrente.py http://localhost

Ate a 1.7 o `rtf_to_text` escrevia o corpo num arquivo de nome FIXO (`input.rtf`) e chamava
o `unrtf` sobre ele. O `/clean` e um `def` sincrono, entao o Starlette da cada pedido a uma
thread do threadpool do uvicorn (processo unico, sem `--workers`): dois pedidos RTF
concorrentes escreviam e liam o mesmo arquivo, e o texto de um paciente saia na resposta
destinada a outro — com os metadados (`fkevolucao`, `nratendimento`) certos, que e o que
torna a troca invisivel no destino. Medido contra a 1.7: 9 de 10 respostas erradas — 5 com o
marcador de outra requisicao e 4 vazias (o `unrtf` falha no arquivo escrito pela metade).
Por isso o teste checa as duas coisas: marcador intruso E marcador proprio ausente.

Os marcadores sao sinteticos de proposito: a corrida se prova sem nenhum dado de paciente.
Eles levam digito no meio para nao terem forma de nome — se o modelo marcasse o marcador,
a redacao o apagaria e o teste passaria a medir outra coisa.
"""
import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

N = 10
# Nome no corpo para o pedido exercitar a redacao tambem, e nao so o unrtf. Inventado.
RTF = (r"{\rtf1\ansi\deff0 M%dK paciente Fulana Beltrano, 74 anos, "
       r"segue estavel no leito. F%dM\par}")


def clean(base, i):
    req = urllib.request.Request(
        f"{base.rstrip('/')}/clean",
        data=json.dumps({"fkevolucao": i, "text": RTF % (i, i), "format": "rtf"}).encode(),
        method="PUT", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status, json.loads(r.read())


def main(base):
    with ThreadPoolExecutor(max_workers=N) as pool:
        respostas = list(pool.map(lambda i: clean(base, i), range(N)))

    falhas = []
    for i, (st, corpo) in enumerate(respostas):
        texto = corpo.get("texto", "")
        if st != 200:
            falhas.append(f"pedido {i}: status {st} ({corpo})")
            continue
        # A troca de PHI: o marcador de OUTRO pedido nesta resposta. E o unico assert que
        # falha pelo bug — os outros dois so garantem que o teste mede o que diz medir.
        intrusos = [j for j in range(N) if j != i and f"M{j}K" in texto]
        if intrusos:
            falhas.append(f"pedido {i}: texto de OUTRA requisicao {intrusos} -> {texto!r}")
        if f"M{i}K" not in texto or f"F{i}M" not in texto:
            falhas.append(f"pedido {i}: perdeu o proprio marcador -> {texto!r}")
        if corpo.get("fkevolucao") != i:
            falhas.append(f"pedido {i}: fkevolucao {corpo.get('fkevolucao')!r}")
        if "***" not in texto:
            falhas.append(f"pedido {i}: o nome do corpo nao foi redigido -> {texto!r}")

    if falhas:
        print(f"FALHOU ({len(falhas)} de {N} pedidos com problema):")
        for f in falhas:
            print(" -", f)
        return 1
    print(f"ok: {N} pedidos RTF simultaneos, cada resposta com o proprio texto")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost"))
