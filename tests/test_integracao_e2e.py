"""Testes de integração ponta a ponta entre os 5 processos reais (Gateway + 4 microsserviços).

Cada microsserviço sobe como processo Uvicorn independente em porta própria e com banco SQLite isolado.
Se REDIS_URL estiver disponível no ambiente, também valida o fluxo assíncrono completo via Redis Streams.
"""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import redis

RAIZ = Path(__file__).resolve().parent.parent
SERVICOS = RAIZ / "servicos"


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _aguardar_saude(url: str, timeout_s: float = 15.0) -> None:
    fim = time.monotonic() + timeout_s
    while time.monotonic() < fim:
        try:
            r = httpx.get(f"{url}/saude", timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.15)
    raise RuntimeError(f"Serviço em {url} não respondeu /saude a tempo.")


def _iniciar_servico(nome: str, porta: int, env_extra: dict[str, str], log_dir: Path) -> subprocess.Popen:
    env = {**os.environ, **env_extra}
    log_path = log_dir / f"{nome}.log"
    arq_log = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(porta)],
        cwd=str(SERVICOS / nome),
        env=env,
        stdout=arq_log,
        stderr=subprocess.STDOUT,
    )
    proc._log_file = arq_log  # type: ignore[attr-defined]
    _aguardar_saude(f"http://127.0.0.1:{porta}")
    return proc


def _encerrar(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    finally:
        arq = getattr(proc, "_log_file", None)
        if arq is not None:
            arq.close()


def _redis_disponivel(url: str) -> bool:
    if not url:
        return False
    try:
        c = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        return bool(c.ping())
    except Exception:
        return False


@pytest.fixture(scope="module")
def stack_microsservicos(tmp_path_factory):
    dados = tmp_path_factory.mktemp("bancos_isolados")
    segredo = secrets.token_urlsafe(48)
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not _redis_disponivel(redis_url):
        redis_url = ""

    portas = {s: _porta_livre() for s in ("usuarios", "inventario", "chamados", "notificacoes", "gateway")}
    urls = {s: f"http://127.0.0.1:{p}" for s, p in portas.items()}
    stream_teste = f"helpdesk:eventos:e2e:{secrets.token_hex(4)}"

    comum = {
        "JWT_SEGREDO": segredo,
        "DADOS_EXEMPLO": "1",
        "SENHA_EXEMPLO": "Helpdesk2026",
        "DOCS": "0",
        "REDIS_URL": redis_url,
        "EVENTOS_STREAM": stream_teste,
    }

    procs: dict[str, subprocess.Popen] = {}
    env_inventario = {**comum, "DATABASE_URL": f"sqlite:///{(dados / 'inventario.db').as_posix()}"}
    try:
        procs["usuarios"] = _iniciar_servico(
            "usuarios",
            portas["usuarios"],
            {**comum, "DATABASE_URL": f"sqlite:///{(dados / 'usuarios.db').as_posix()}"},
            dados,
        )
        procs["inventario"] = _iniciar_servico("inventario", portas["inventario"], env_inventario, dados)
        procs["chamados"] = _iniciar_servico(
            "chamados",
            portas["chamados"],
            {
                **comum,
                "DATABASE_URL": f"sqlite:///{(dados / 'chamados.db').as_posix()}",
                "USUARIOS_URL": urls["usuarios"],
                "INVENTARIO_URL": urls["inventario"],
                "HTTP_TIMEOUT_SEGUNDOS": "1.5",
                "CIRCUIT_BREAKER_LIMITE_FALHAS": "2",
                "CIRCUIT_BREAKER_RESET_SEGUNDOS": "2.0",
            },
            dados,
        )
        procs["notificacoes"] = _iniciar_servico(
            "notificacoes",
            portas["notificacoes"],
            {
                **comum,
                "DATABASE_URL": f"sqlite:///{(dados / 'notificacoes.db').as_posix()}",
                "EVENTOS_GRUPO": f"grupo-{secrets.token_hex(4)}",
            },
            dados,
        )
        procs["gateway"] = _iniciar_servico(
            "gateway",
            portas["gateway"],
            {
                "DOCS": "0",
                "USUARIOS_URL": urls["usuarios"],
                "INVENTARIO_URL": urls["inventario"],
                "CHAMADOS_URL": urls["chamados"],
                "NOTIFICACOES_URL": urls["notificacoes"],
            },
            dados,
        )

        yield {
            "gateway": urls["gateway"],
            "dados": dados,
            "procs": procs,
            "portas": portas,
            "env_inventario": env_inventario,
            "redis_ativo": bool(redis_url),
        }
    finally:
        for p in procs.values():
            _encerrar(p)


def _login(gw: str, email: str, senha: str = "Helpdesk2026") -> tuple[dict[str, str], int]:
    r = httpx.post(f"{gw}/auth/login", json={"email": email, "senha": senha}, timeout=5.0)
    assert r.status_code == 200, r.text
    dados = r.json()
    return {"Authorization": f"Bearer {dados['access_token']}"}, dados["usuario"]["id"]


def test_bancos_separados_e_saude_agregada(stack_microsservicos):
    dados = stack_microsservicos["dados"]
    for arquivo in ("usuarios.db", "inventario.db", "chamados.db", "notificacoes.db"):
        assert (dados / arquivo).exists()

    saude = httpx.get(f"{stack_microsservicos['gateway']}/saude", timeout=5.0)
    assert saude.status_code == 200
    body = saude.json()
    assert body["status"] == "ok"
    assert set(body["servicos"]) == {"usuarios", "inventario", "chamados", "notificacoes"}


def test_seguranca_e_fluxo_completo_pelo_gateway(stack_microsservicos):
    gw = stack_microsservicos["gateway"]

    # Sem token -> 401 em todos os serviços via Gateway
    for rota in ("/usuarios", "/ativos", "/chamados", "/notificacoes", "/auth/eu"):
        assert httpx.get(f"{gw}{rota}", timeout=3.0).status_code == 401

    h_ana, ana_id = _login(gw, "ana@empresa.com")
    h_bruno, _ = _login(gw, "bruno@empresa.com")
    h_carla, carla_id = _login(gw, "carla@empresa.com")

    # Tela HTML servida pelo Gateway
    tela = httpx.get(f"{gw}/", timeout=3.0)
    assert tela.status_code == 200 and "HelpDesk TI" in tela.text

    # Ana abre chamado referenciando equipamento (Chamados -> Inventário via HTTP)
    aberto = httpx.post(
        f"{gw}/chamados",
        headers={**h_ana, "X-Request-ID": "e2e_fluxo_1"},
        json={"titulo": "Monitor piscando", "descricao": "Cabo HDMI frouxo", "prioridade": "alta", "ativo_id": 1},
        timeout=5.0,
    )
    assert aberto.status_code == 201, aberto.text
    assert aberto.headers["x-request-id"] == "e2e_fluxo_1"
    cid = aberto.json()["id"]

    # Bruno (outro solicitante) não pode ver o chamado da Ana -> 404
    assert httpx.get(f"{gw}/chamados/{cid}", headers=h_bruno, timeout=3.0).status_code == 404

    # Carla atribui para si (Chamados -> Usuários via HTTP), comenta, resolve e Ana fecha
    atrib = httpx.patch(
        f"{gw}/chamados/{cid}/atribuir",
        headers=h_carla,
        json={"tecnico_id": carla_id},
        timeout=5.0,
    )
    assert atrib.status_code == 200 and atrib.json()["status"] == "em_atendimento"

    com = httpx.post(f"{gw}/chamados/{cid}/comentarios", headers=h_carla, json={"texto": "Cabo trocado."}, timeout=3.0)
    assert com.status_code == 201 and com.json()["autor_id"] == carla_id

    res = httpx.patch(f"{gw}/chamados/{cid}/status", headers=h_carla, json={"status": "resolvido"}, timeout=3.0)
    assert res.status_code == 200 and res.json()["status"] == "resolvido"

    fec = httpx.patch(f"{gw}/chamados/{cid}/status", headers=h_ana, json={"status": "fechado"}, timeout=3.0)
    assert fec.status_code == 200 and fec.json()["status"] == "fechado"

    # Se Redis estiver ativo (CI / Docker), confirma consistência eventual em Notificações
    if stack_microsservicos["redis_ativo"]:
        fim = time.monotonic() + 4.0
        tipos_ana = []
        while time.monotonic() < fim:
            avisos = httpx.get(f"{gw}/notificacoes", headers=h_ana, timeout=3.0).json()
            tipos_ana = [a["tipo"] for a in avisos if f"#{cid}" in a["mensagem"]]
            if "ChamadoAberto" in tipos_ana and "ChamadoResolvido" in tipos_ana:
                break
            time.sleep(0.2)
        assert "ChamadoAberto" in tipos_ana and "ChamadoResolvido" in tipos_ana


def test_falha_e_recuperacao_do_inventario(stack_microsservicos):
    gw = stack_microsservicos["gateway"]
    h_ana, _ = _login(gw, "ana@empresa.com")

    # Derruba o processo real do Inventário
    _encerrar(stack_microsservicos["procs"]["inventario"])
    stack_microsservicos["procs"]["inventario"] = None

    try:
        # Saúde agregada mostra inventário offline
        saude = httpx.get(f"{gw}/saude", timeout=5.0).json()
        assert saude["status"] == "degradado"
        assert saude["servicos"]["inventario"]["status"] == "offline"

        # Usuários e Chamados continuam respondendo normalmente
        assert httpx.get(f"{gw}/usuarios", headers=h_ana, timeout=3.0).status_code == 200
        assert httpx.get(f"{gw}/chamados", headers=h_ana, timeout=3.0).status_code == 200

        # Abrir chamado sem equipamento continua funcionando mesmo com Inventário fora do ar
        sem_ativo = httpx.post(
            f"{gw}/chamados",
            headers=h_ana,
            json={"titulo": "Dúvida no sistema", "descricao": "Sem equipamento", "prioridade": "baixa"},
            timeout=5.0,
        )
        assert sem_ativo.status_code == 201

        # Abrir chamado COM equipamento falha de forma clara (503) sem travar
        com_ativo = httpx.post(
            f"{gw}/chamados",
            headers=h_ana,
            json={"titulo": "PC travando", "descricao": "Tela azul", "prioridade": "alta", "ativo_id": 1},
            timeout=5.0,
        )
        assert com_ativo.status_code == 503
        assert "Inventário" in com_ativo.json()["detail"]
    finally:
        # Sobe o Inventário novamente e valida recuperação automática após cooldown do Circuit Breaker
        stack_microsservicos["procs"]["inventario"] = _iniciar_servico(
            "inventario",
            stack_microsservicos["portas"]["inventario"],
            stack_microsservicos["env_inventario"],
            stack_microsservicos["dados"],
        )

    time.sleep(2.2)
    recuperado = httpx.post(
        f"{gw}/chamados",
        headers=h_ana,
        json={"titulo": "PC recuperado", "descricao": "Teste pós-retorno", "prioridade": "media", "ativo_id": 1},
        timeout=5.0,
    )
    assert recuperado.status_code == 201
