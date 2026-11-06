# Hélder Sorteios — Landing page editável

Flask + SQLite em Docker. Tudo (textos, imagens, carrossel, botão, links, cores, rodapé, SEO, código de pixel) é editado em **`/admin`**, com prévia ao vivo (computador/celular).

## Branches e portas

| Branch | LP | Porta (container e host) |
|--------|----|--------------------------|
| `lp-1` | LP 1 | **6847** |
| `lp-2` | LP 2 | **5926** |
| `main` | base comum (porta 6847) | — |

As duas branches têm o mesmo código; só mudam a porta no `docker-compose.yml` (3 linhas) e no `Dockerfile`. Mudanças no código vão para `main` e depois `git merge main` em cada branch (os conflitos, se houver, ficam só na porta).

## Deploy no Easypanel (uma aplicação por branch)

1. Crie um serviço **Docker Compose** apontando para o repositório e para a branch (`lp-1` ou `lp-2`).
2. Aba **Ambiente**: `ADMIN_PASSWORD`, `SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`). `SESSION_COOKIE_SECURE` já vem `1`.
3. Aba **Domínios**: o domínio da LP aponta para o serviço `lp`, na porta da tabela acima. O HTTPS é do Easypanel.
4. Deploy. A LP abre em `/` e o painel em `/admin`.

**Sem hairpin:** o app nunca chama o próprio domínio; o healthcheck usa `127.0.0.1` dentro do container. A porta é publicada só em `127.0.0.1` do servidor (o proxy chega pela rede interna do Docker). O app confia nos cabeçalhos `X-Forwarded-*` do proxy (IP real, https).

## Teste local

```bash
cp .env.example .env   # SESSION_COOKIE_SECURE=0 para http://
docker compose up -d --build
```
Abra `http://127.0.0.1:6847` e `/admin`.

## Dados e backup

Volume `lp_data` → `/app/data` (banco `lp.sqlite3` + `uploads/`). Backup:
`docker compose cp lp:/app/data ./backup-lp`

## Segurança

Senha só por variável de ambiente, cookie HttpOnly/Secure, CSRF em todas as ações, bloqueio por IP após 6 tentativas erradas (5 min), validação de cores/links (bloqueia `javascript:`), upload só PNG/JPG/WEBP/GIF com checagem de assinatura e limite de 8 MB. O campo "Código extra no `<head>`" executa para todos os visitantes: só cole código confiável.

## Fontes

"STAGE 2" usa a Sprite Graffiti (licença em `app/static/fonts/`). O título antigo "Petchlamoon" é opcional e não é usado nesta versão.
