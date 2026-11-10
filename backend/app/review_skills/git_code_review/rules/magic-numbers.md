---
title: Evitar números mágicos
severity: Sugestão
tags: legibilidade, manutenção, constantes, enums
---

## Evitar números mágicos

Número mágico é um valor literal cujo significado não fica claro pelo código: um limite, um status, um prazo, um percentual, uma posição em uma estrutura fixa. Quem lê precisa adivinhar o que ele representa e, quando o valor muda, é preciso encontrar e atualizar cada cópia.

Sempre sugira trocar o valor por um nome que o explique: uma constante de classe, um caso de enum ou uma variável com nome representativo.

### Como identificar

- Literais numéricos em condições, cálculos ou argumentos cujo significado depende de uma regra de negócio (`if ($status === 3)`, `$days > 30`, `$price * 0.15`).
- O mesmo literal repetido em vários lugares com o mesmo significado.
- Números que representam estados, tipos ou categorias, que normalmente pertencem a um enum.
- Literais de texto usados da mesma forma (nomes de status, códigos de tipo) seguem a mesma regra.

### Exceções

- `0`, `1` e `-1` em contextos óbvios, como contadores, primeiro elemento ou incremento.
- Valores cujo significado fica claro por um argumento nomeado ou uma variável na mesma linha.
- Dados e valores esperados em testes, a não ser que repitam uma regra de negócio que já tem constante.
- Valores definidos por um padrão conhecido e usados por uma constante do framework, como códigos HTTP em um helper de resposta.

### Como sugerir

- Prefira o que já existe no projeto: procure um enum ou uma constante com esse significado antes de sugerir um novo (por exemplo, em uma pasta de enums do projeto).
- Use enum para um conjunto fechado de estados ou tipos, constante de classe para um valor fixo de negócio e variável para um valor calculado localmente.
- Sugira um nome que descreva o significado, não o valor (`MAX_LOGIN_ATTEMPTS`, e não `FIVE`).

**Incorreto:**

```php
if ($attempts >= 5) {
    $this->lockAccount($userId, 30);
}
```

**Correto:**

```php
private const MAX_LOGIN_ATTEMPTS = 5;
private const LOCK_DURATION_MINUTES = 30;

if ($attempts >= self::MAX_LOGIN_ATTEMPTS) {
    $this->lockAccount($userId, self::LOCK_DURATION_MINUTES);
}
```

**Incorreto:**

```js
if (item.status === 2) {
  showBadge(item);
}
```

**Correto:**

```js
const ITEM_STATUS = Object.freeze({ PENDING: 1, ACTIVE: 2 });

if (item.status === ITEM_STATUS.ACTIVE) {
  showBadge(item);
}
```
