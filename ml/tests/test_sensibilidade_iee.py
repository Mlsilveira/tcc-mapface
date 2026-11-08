"""O replay do IEE precisa ser a produção, e só depois virar análise."""
import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

import sensibilidade_iee as si

INICIO = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
INICIO_MS = INICIO.timestamp() * 1000


def _iso(segundos):
    return (INICIO + timedelta(seconds=segundos)).isoformat()


def _gravacao(perfil, duracao=600):
    """`perfil(segundo)` devolve os campos do payload. Scores vêm da produção."""
    enviados = [
        {"t": INICIO_MS + s * 1000, "i_conexao": 0, "mar": 0.05, "incerteza": None,
         "rosto_detectado": True, **perfil(s)}
        for s in range(duracao)
    ]
    dados = {"enviados": enviados, "recebidos": []}
    for ponto in si.reproduzir(si.ler_leituras(dados), *si.CENARIO_PADRAO):
        dados["recebidos"].append(
            {"tipo": "score", "i_envio": ponto.indice_envio, "score": ponto.score}
        )
    return dados


def _estavel(segundo):
    return {"ear": 0.30, "yaw": 0.0}


def _blocos():
    return [
        {"indice": 1, "tipo": "foco", "inicio": _iso(60), "fim": _iso(240)},
        {"indice": 2, "tipo": "pausa", "inicio": _iso(240), "fim": _iso(300)},
        {"indice": 3, "tipo": "foco", "inicio": _iso(300), "fim": _iso(600)},
    ]


def _cruzamento(segundo):
    """Foco 1 com olhos melhores; foco 2 com a cabeça melhor. A ordem depende do peso."""
    if segundo < 60:
        return {"ear": 0.30, "yaw": 0.0}
    if segundo < 300:
        return {"ear": 0.27, "yaw": 13.5}  # ocular 0,90 · orientação 0,70
    return {"ear": 0.24, "yaw": 4.5}  # ocular 0,80 · orientação 0,90


def _focos():
    return si.blocos_de_foco(si.ler_blocos(_blocos()))


def test_cenario_padrao_reproduz_o_analista_de_producao():
    from app import analista

    dados = _gravacao(_estavel, duracao=90)
    pontos = si.reproduzir(si.ler_leituras(dados), *si.CENARIO_PADRAO)

    engajamento = analista.AnalistaEngajamento()
    for leitura, ponto in zip(si.ler_leituras(dados), pontos):
        resultado = engajamento.observar(
            ear=leitura.ear, yaw=leitura.yaw, agora=leitura.instante, mar=leitura.mar
        )
        assert ponto.score == pytest.approx(resultado.score)


def test_constantes_voltam_ao_original_mesmo_com_erro():
    from app import analista

    originais = (analista.PESO_OCULAR, analista.PESO_ORIENTACAO, analista.FRACAO_OLHO_FECHADO)

    with pytest.raises(RuntimeError):
        with si._constantes(0.1, 0.9, 0.2):
            assert analista.PESO_OCULAR == 0.1
            raise RuntimeError

    assert (
        analista.PESO_OCULAR, analista.PESO_ORIENTACAO, analista.FRACAO_OLHO_FECHADO
    ) == originais


def test_cada_peso_altera_o_score_na_proporcao_certa():
    dados = _gravacao(lambda s: _estavel(s) if s < 60 else {"ear": 0.15, "yaw": 0.0}, duracao=62)
    leituras = si.ler_leituras(dados)

    # Ocular 0,5 e orientação 1,0; o limiar baixo evita fechar o olho nesse EAR.
    assert si.reproduzir(leituras, 0.5, 0.5, 0.4)[-1].score == pytest.approx(75.0)
    assert si.reproduzir(leituras, 0.7, 0.3, 0.4)[-1].score == pytest.approx(65.0)


def test_limiar_decide_se_o_olho_conta_como_fechado():
    """EAR a 45% do neutro: fechado com limiar de 50% e aberto com o de 40%."""

    def perfil(segundo):
        return _estavel(segundo) if segundo < 60 else {"ear": 0.135, "yaw": 0.0}

    leituras = si.ler_leituras(_gravacao(perfil, duracao=100))

    com_limiar_alto = si.reproduzir(leituras, 0.6, 0.4, 0.5)[-1].score
    com_limiar_baixo = si.reproduzir(leituras, 0.6, 0.4, 0.4)[-1].score

    assert com_limiar_baixo > com_limiar_alto


def test_ponto_incerto_fica_fora_da_media():
    bloco = si.Bloco(1, "foco", INICIO, INICIO + timedelta(seconds=200), None)
    pontos = [
        si.Ponto(i, INICIO + timedelta(seconds=i), None if i % 2 else 80.0) for i in range(200)
    ]

    assert si.media_do_bloco(bloco, pontos) == pytest.approx(80.0)


def test_bloco_com_pouca_medida_nao_tem_media():
    bloco = si.Bloco(1, "foco", INICIO, INICIO + timedelta(seconds=59), None)
    pontos = [si.Ponto(i, INICIO + timedelta(seconds=i), 80.0) for i in range(59)]

    assert si.media_do_bloco(bloco, pontos) is None


def test_borda_do_bloco_e_semiaberta():
    bloco = si.Bloco(1, "foco", INICIO, INICIO + timedelta(seconds=60), None)
    pontos = [si.Ponto(i, INICIO + timedelta(seconds=i), 50.0) for i in range(60)]
    pontos.append(si.Ponto(60, INICIO + timedelta(seconds=60), 100.0))

    assert si.media_do_bloco(bloco, pontos) == pytest.approx(50.0)


def test_ordem_ignora_bloco_sem_media():
    assert si.ordem_dos_blocos({1: 60.0, 2: None, 3: 70.0}) == (3, 1)


def test_detecta_a_troca_de_ordem_entre_cenarios():
    cenarios = si.calcular_cenarios(si.ler_leituras(_gravacao(_cruzamento)), _focos())

    assert len(cenarios) == 9
    por_peso = {c.peso_ocular: c.ordem for c in cenarios if c.limiar == 0.5}
    assert por_peso[0.7] == (1, 3)
    assert por_peso[0.5] == (3, 1)
    assert si.cenarios_com_ordem_diferente(cenarios)
    assert "mudou" in si.conclusao(cenarios, _focos())


def test_afirma_estabilidade_quando_a_ordem_se_mantem():
    def perfil(segundo):
        if segundo < 60 or segundo >= 300:
            return {"ear": 0.30, "yaw": 0.0}
        return {"ear": 0.24, "yaw": 13.5}

    cenarios = si.calcular_cenarios(si.ler_leituras(_gravacao(perfil)), _focos())

    assert si.cenarios_com_ordem_diferente(cenarios) == []
    assert "a mesma nos 9 cenários" in si.conclusao(cenarios, _focos())


def test_pausa_nao_entra_na_comparacao():
    assert [bloco.indice for bloco in _focos()] == [1, 3]


def test_recusa_gravacao_que_nao_reproduz_a_producao(tmp_path):
    dados = _gravacao(_estavel)
    for item in dados["recebidos"]:
        item["score"] = 10.0
    sessao, blocos = tmp_path / "s.json", tmp_path / "b.json"
    sessao.write_text(json.dumps(dados))
    blocos.write_text(json.dumps(_blocos()))

    with pytest.raises(si.ErroDeEntrada, match="não reproduziu"):
        si.analisar(sessao, blocos, "Teste", tmp_path / "saida")
    assert not (tmp_path / "saida").exists()


def test_recusa_gravacao_sem_scores(tmp_path):
    dados = _gravacao(_estavel)
    dados["recebidos"] = []
    sessao, blocos = tmp_path / "s.json", tmp_path / "b.json"
    sessao.write_text(json.dumps(dados))
    blocos.write_text(json.dumps(_blocos()))

    with pytest.raises(si.ErroDeEntrada, match="não reproduziu"):
        si.analisar(sessao, blocos, "Teste", tmp_path / "saida")


@pytest.mark.parametrize(
    "conteudo, trecho",
    [
        ("{nao e json", "JSON"),
        ('{"recebidos": []}', "enviados"),
        ('{"enviados": []}', "nenhum payload"),
    ],
    ids=["json-invalido", "sem-enviados", "vazio"],
)
def test_erro_claro_com_sessao_invalida(tmp_path, capsys, conteudo, trecho):
    sessao, blocos = tmp_path / "s.json", tmp_path / "b.json"
    sessao.write_text(conteudo)
    blocos.write_text(json.dumps(_blocos()))

    assert si.main(["--sessao", str(sessao), "--blocos", str(blocos), "-o", str(tmp_path)]) == 2
    assert trecho in capsys.readouterr().err


def test_erro_claro_sem_bloco_de_foco():
    with pytest.raises(si.ErroDeEntrada, match="bloco de foco"):
        si.blocos_de_foco(si.ler_blocos([_blocos()[1]]))


def test_de_ponta_a_ponta_gera_os_artefatos(tmp_path):
    sessao, blocos = tmp_path / "s.json", tmp_path / "b.json"
    sessao.write_text(json.dumps(_gravacao(_cruzamento)))
    blocos.write_text(json.dumps({"id_sessao": 1, "blocos": _blocos()}))
    saida = tmp_path / "saida"

    assert si.main(["--sessao", str(sessao), "--blocos", str(blocos), "-o", str(saida)]) == 0

    for nome in ("resultado.csv", "relatorio.md", "sensibilidade_iee.png", "sensibilidade_iee.svg"):
        assert (saida / nome).stat().st_size > 0
    with open(saida / "resultado.csv", encoding="utf-8") as arquivo:
        assert len(list(csv.DictReader(arquivo))) == 18
