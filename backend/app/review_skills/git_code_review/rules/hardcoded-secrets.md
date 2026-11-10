---
title: Sem segredos no código
severity: Bloqueante
tags: segurança, credenciais, configuração
---

## Sem segredos no código

Segredos são valores que dão acesso a algum sistema: senhas, tokens, chaves de API, chaves privadas, segredos de assinatura (HMAC, JWT) e strings de conexão com usuário e senha. Quando entram no código, ficam no histórico do Git para sempre e passam a ser vistos por qualquer pessoa com acesso ao repositório, aos forks, aos logs de CI e às cópias locais.

Todo segredo deve vir da configuração do ambiente (variáveis de ambiente, arquivos `.env` fora do controle de versão ou um gerenciador de segredos), nunca de um valor escrito no código.

### Como identificar

- Variáveis, constantes, propriedades ou chaves de configuração com nomes como `password`, `secret`, `token`, `api_key`, `apiKey`, `private_key`, `client_secret` ou `auth` recebendo um valor literal.
- Strings de conexão com credenciais (`mysql://usuario:senha@host`, `postgres://...`, `redis://:senha@...`).
- Cabeçalhos de autenticação com valor fixo (`Authorization: Bearer ...`, `X-Api-Key: ...`).
- Blocos de chave privada (`-----BEGIN PRIVATE KEY-----`, `-----BEGIN RSA PRIVATE KEY-----`).
- Tokens com formato conhecido de provedores (por exemplo, prefixos como `ghp_`, `sk_live_`, `AKIA`, `xoxb-`).
- Arquivos `.env`, de credenciais ou de certificado adicionados ao PR, ou valores reais copiados para `.env.example`, testes, fixtures, seeds, documentação e scripts.
- Valores sensíveis concatenados em URLs (`?token=...`, `?key=...`).

### Exceções

- Placeholders evidentes em arquivos de exemplo (`.env.example`, documentação): valor vazio ou algo como `<sua-chave-aqui>` e `changeme`.
- Valores claramente falsos em testes (`test-secret`, `fake-token`), desde que não sejam aceitos por nenhum ambiente real.
- Identificadores públicos por natureza, que o próprio provedor documenta como seguros para o cliente (por exemplo, chaves publicáveis de pagamento ou IDs públicos de analytics). Na dúvida, reporte como dúvida.
- Nomes de variáveis de ambiente sem o valor (`getenv('API_KEY')`, `process.env.API_KEY`).

### Como sugerir

- Mover o valor para a configuração do ambiente, usando o mecanismo que o projeto já tem (por exemplo, o carregamento de `.env` ou a classe de configuração existente), e adicionar a chave sem valor no `.env.example`.
- Deixar claro que remover o valor em um novo commit não basta: o segredo já está no histórico do Git e precisa ser trocado (rotacionado) no sistema de origem.
- Nunca repetir o valor do segredo no comentário da review. Aponte a linha e descreva o tipo de segredo, sem copiar nem mostrar parte do valor.

**Incorreto:**

```php
$client = new PaymentClient('<valor-da-chave-escrito-no-código>');
```

**Correto:**

```php
$client = new PaymentClient(getenv('PAYMENT_API_KEY'));
```

**Incorreto:**

```js
const response = await fetch(url, {
  headers: { Authorization: 'Bearer <token-escrito-no-código>' },
});
```

**Correto:**

```js
const response = await fetch(url, {
  headers: { Authorization: `Bearer ${process.env.API_TOKEN}` },
});
```
