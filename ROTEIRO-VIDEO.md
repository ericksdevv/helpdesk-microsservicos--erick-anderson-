# Roteiro para o vídeo de demonstração (4 a 6 minutos)

Este roteiro segue exatamente a ordem pedida em [DESAFIO.md](DESAFIO.md).
Você pode gravar a tela com áudio usando OBS Studio, Clipchamp (nativo no Windows 11) ou gravador do navegador, e publicar como **Não listado** no YouTube ou no Google Drive com acesso para quem tiver o link.

> **Lembrete antes de entregar:** cole o link do vídeo no topo do [README.md](README.md) e envie ao professor o link do repositório + link do vídeo até **25/11/2026**.

---

## Checklist rápido antes de gravar

- Abra o terminal na pasta do projeto (`helpdesk-microsservicos-erick`).
- Abra o `README.md` no VS Code (ou no GitHub) mostrando o diagrama Mermaid renderizado.
- Abra o navegador em `http://localhost:8000`.
- Deixe outro terminal aberto para os comandos `docker compose` e `curl.exe`.

---

## Parte 1 · A arquitetura (~45s)

**Mostrar:** diagrama Mermaid no `README.md` e estrutura da pasta `servicos/`.

**O que falar:**
- "Antes o HelpDesk TI era um monólito com um único processo e um único banco SQLite."
- "Separei o sistema em **5 componentes independentes** dentro de `servicos/`: `gateway`, `usuarios`, `inventario`, `chamados` e `notificacoes`, além do `redis` como barramento de eventos e rate limit distribuído."
- "Cada microsserviço tem seu próprio código, `Dockerfile`, dependências, testes e banco isolado, sem chaves estrangeiras entre bancos."
- "Só o **API Gateway** publica a porta `8000`. Os outros serviços e o Redis ficam apenas na rede interna `helpdesk-rede`."
- "Quando `chamados` precisa validar um equipamento ou técnico, ele chama `inventario` ou `usuarios` por HTTP com `timeout`, `Circuit Breaker`, repassando `Authorization` e `X-Request-ID`. E para notificações, ele grava na tabela Outbox e publica eventos no **Redis Streams** para o serviço `notificacoes` consumir de forma assíncrona com idempotência e Dead Letter Queue."

---

## Parte 2 · Tudo subindo com Docker (~45s)

**Executar no terminal:**
```bash
docker compose up --build -d
docker compose ps
```

**O que mostrar e falar:**
- Mostre todos os contêineres subindo (`init-segredo`, `redis`, `usuarios`, `inventario`, `chamados`, `notificacoes`, `gateway`).
- No `docker compose ps`, destaque que todos aparecem como `Up (healthy)` e que **apenas o `gateway` tem porta `127.0.0.1:8000->8000` publicada**.

---

## Parte 3 · Fluxo completo pela tela (~1min15s)

**Mostrar no navegador (`http://localhost:8000`):**
1. Mostre a barra **Saúde dos microsserviços** no topo após entrar.
2. Faça login como **`carla@empresa.com`** (senha `Helpdesk2026`).
3. **Abrir chamado:** crie um chamado escolhendo um equipamento (ex: `PAT-0001`). Mostre que ele aparece na lista e que a notificação `ChamadoAberto` aparece em **Minhas notificações** (via evento assíncrono).
4. **Atribuir:** selecione Carla no chamado recém-criado e clique em **Atribuir** (`aberto` -> `em atendimento`). Mostre a notificação `ChamadoAtribuido`.
5. **Comentar e Resolver:** clique em **Detalhes**, envie um comentário, feche o modal e clique em **Resolver**.
6. **Fechar:** clique em **Fechar** (`resolvido` -> `fechado`).

---

## Parte 4 · Segurança funcionando (~45s)

**Executar no terminal (ou PowerShell usando `curl.exe`):**

1. Chamada sem token recebe `401`:
```bash
curl.exe -i http://localhost:8000/chamados
```

2. Login com **Ana** (`ana@empresa.com`) e tentativa de acessar chamado do **Bruno** (ID `2`, criado nos dados de exemplo para o Bruno):
```powershell
$loginAna = Invoke-RestMethod -Method Post -Uri http://localhost:8000/auth/login -ContentType "application/json" -Body '{"email":"ana@empresa.com","senha":"Helpdesk2026"}'
$tokenAna = $loginAna.access_token
curl.exe -i -H "Authorization: Bearer $tokenAna" http://localhost:8000/chamados/2
```
- Mostre o retorno **`404 Not Found`** (não vaza que o chamado existe) e que `GET /chamados` mostra só os chamados da Ana.
- Destaque também que o segredo `JWT_SEGREDO` não está no código: vem do `.env` ou é gerado em tempo de execução pelo `init-segredo`.

---

## Parte 5 · Bancos separados (~30s)

**Executar no terminal:**
```bash
docker volume ls
```
Mostre os volumes separados:
- `dados_usuarios`
- `dados_inventario`
- `dados_chamados`
- `dados_notificacoes`
- `dados_redis`

E se quiser comprovar ainda mais, liste os arquivos dentro de dois contêineres diferentes:
```bash
docker compose exec usuarios ls -lh /dados
docker compose exec chamados ls -lh /dados
```

---

## Parte 6 · Falha e recuperação de um serviço (~1min)

**Executar no terminal:**
```bash
docker compose stop inventario
```

**Mostrar na tela e/ou terminal:**
1. Atualize a tela (botão **Atualizar**): a barra de saúde mostra **`Inventário · offline`**, enquanto `Usuários`, `Chamados` e `Notificações` continuam **`ok`**.
2. Mostre que a lista de chamados e usuários continua funcionando normalmente (e até abrir chamado **sem** equipamento continua funcionando).
3. Tente abrir um chamado **com equipamento** selecionado: o sistema responde com erro **`503`** claro (*"Serviço de Inventário indisponível no momento..."*) sem travar a aplicação.
4. Suba o serviço novamente e mostre a recuperação:
```bash
docker compose start inventario
```
Aguarde ~5 segundos, clique em **Atualizar** na tela e abra o chamado com equipamento novamente com sucesso.

---

## Parte 7 e 8 · O que mudou + Bônus e testes (~45s)

**O que falar:**
- **Melhorias vs monólito:** cada serviço tem deploy e banco independentes, falhas são isoladas (`timeout` + `Circuit Breaker` + `Outbox`), e notificações não bloqueiam nem derrubam chamados (`docker compose stop notificacoes` não impede abrir chamados!).
- **Novos desafios:** comunicação via rede pode falhar ou atrasar, exigindo timeout, consistência eventual nas notificações e proteção contra duplicação (`event_id`) + `DLQ`.
- **Bônus:** mostre a rota `/saude` do Gateway (`curl.exe http://localhost:8000/saude`), os eventos no Redis/Notificações e, se quiser, rode `pytest -q` em um dos serviços (`servicos/chamados`) ou mostre o workflow `.github/workflows/testes.yml`.
