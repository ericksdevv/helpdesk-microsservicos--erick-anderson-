# Segurança na arquitetura em microsserviços

Este documento detalha os controles mantidos e reforçados após a separação do monólito em microsserviços.

## O que está protegido

| Risco | Proteção |
|---|---|
| Acesso sem login | Todo microsserviço valida o JWT (`Authorization: Bearer ...`) de forma independente antes de responder, exceto `/auth/login` e `/saude`. |
| Exposição interna de serviços e bancos | Apenas o **API Gateway** publica porta (`127.0.0.1:8000:8000`). Usuários, Inventário, Chamados, Notificações e Redis ficam isolados na rede interna `helpdesk-rede`. |
| Segredo JWT no código | `JWT_SEGREDO` vem exclusivamente de variável de ambiente (`.env`) ou de arquivo em volume gerado em runtime pelo `init-segredo` e montado como `:ro`. |
| Token falsificado ou `alg: none` | Todos os serviços exigem `HS256`, `iss="helpdesk-ti"`, claims obrigatórias (`exp`, `iat`, `sub`, `iss`, `perfil`) e perfil válido. |
| Senhas vazadas e força bruta | Hashes **scrypt** com sal aleatório e comparação `hmac.compare_digest`. Limite de 5 falhas distribuído no **Redis** usando hash SHA-256 de `email|ip` (sem PII na chave), com fallback em memória se o Redis cair. |
| Permissões por perfil e IDOR/BOLA | Solicitante vê/comenta/fecha apenas os próprios chamados (chamado de outro usuário retorna `404`) e lê apenas as próprias notificações; `solicitante_id` e `autor_id` vêm sempre do JWT, nunca do corpo da requisição; campos extras são rejeitados (`extra="forbid"`). |
| XSS e Clickjacking | Toda string vinda das APIs passa por `esc()` em `app.js`, sem scripts inline ou `onclick`; Gateway aplica `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` e `Cross-Origin-Opener-Policy`. |
| Payloads abusivos e SQL Injection | Limite de 64 KB (`413`) aplicado tanto no Gateway quanto em cada microsserviço; persistência exclusivamente via SQLAlchemy parametrizado, em 4 bancos separados. |
| Rastreabilidade e logs seguros | `X-Request-ID` validado/gerado no Gateway e propagado em chamadas HTTP e eventos; logs não registram tokens, senhas ou payloads sensíveis. |
| Contêineres endurecidos | Todos os serviços Python rodam com usuário sem privilégios (`uid 10001`), `read_only: true`, `tmpfs: /tmp`, `no-new-privileges:true` e `cap_drop: ALL`. |

## Checklist antes de usar em produção

- Defina `JWT_SEGREDO` explícito no `.env` com pelo menos 32 caracteres aleatórios.
- Rode com `DADOS_EXEMPLO=0` e `DOCS=0`.
- Publique o Gateway atrás de HTTPS (TLS).
- Substitua `sqlite://` por bancos PostgreSQL dedicados por microsserviço e proteja o Redis com senha (`requirepass`) e TLS.
