"""Formas clínicas que o modelo marcou como nome em produção (11/2026).

Medição: 267 evoluções reais, 30 dias, texto original do HIS passado pelo serviço
com e sem a blocklist nova (mesma imagem, mesmo pacote o1.3). Resultado:
  - carvedilol: 2 de 84 ocorrências mascaradas sem a lista, 0 com ela;
  - drenado: 2 de 10 mascaradas sem a lista; o modelo marca o span "(DRENADO",
    com o parêntese de abertura e sem o de fechamento. A pontuação de borda sai
    antes da comparação (`blocklist.e_bloqueado`), e a forma `(drenado` também
    está na lista, explícita;
  - total de spans redigidos: 139 sem a lista, 136 com ela. A diferença é só
    dos termos da lista: nenhum nome deixou de ser redigido.
kdigo, gentamicina, iamcsst e aerolin foram relatados por usuário e não
tiveram ocorrência mascarada na janela medida; entram como prevenção.

Sem runtime nem bs4, como o `test_blocklist.py`: roda no CI antes do build
(`python3 app/test_blocklist_termos_clinicos.py`). Os nomes aqui são inventados.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blocklist import carrega, e_bloqueado, filtra  # noqa: E402

BL = carrega()

TERMOS = ["carvedilol", "kdigo", "gentamicina", "iamcsst", "aerolin",
          "drenado", "(drenado"]


def test_termos_estao_na_lista():
    faltando = [t for t in TERMOS if t not in BL]
    assert not faltando, f"faltam na blocklist: {faltando}"


def test_comparacao_ignora_caixa_e_espaco():
    for span in ["CARVEDILOL", "Carvedilol", " kdigo ", "IAMCSST"]:
        assert e_bloqueado(span, BL), span


def test_pontuacao_nas_pontas():
    # "(DRENADO" é o span que o modelo devolve em produção: parêntese de abertura
    # dentro, o de fechamento fora.
    for span in ["(DRENADO", "(DRENADO)", "(Carvedilol", "KDIGO,", "gentamicina."]:
        assert e_bloqueado(span, BL), span


def test_forma_inteira_nao_substring():
    # a lista não pode apagar span que só CONTÉM o termo
    for span in ["Drenadoro", "Kdigolândia", "Carvedilolson"]:
        assert not e_bloqueado(span, BL), span


def test_filtra_mantem_nome_e_remove_termo():
    spans = [{"texto": "(DRENADO"}, {"texto": "CARVEDILOL"},
             {"texto": "Fulano de Tal"}, {"texto": "Dr. Beltrano"}]
    restantes = [s["texto"] for s in filtra(spans, BL)]
    assert restantes == ["Fulano de Tal", "Dr. Beltrano"], restantes


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print("ok", nome)
