---
title: Sem código morto
severity: Sugestão
tags: limpeza, manutenção, legibilidade
---

## Sem código morto

Código morto é o que existe no código mas não é usado nem executado: blocos comentados, imports e variáveis sem uso, trechos que nunca rodam. Ele não muda o comportamento, mas confunde quem lê, porque parece ter uma função que não tem, e precisa ser mantido sem motivo.

Esta regra vale apenas quando o código morto não afeta o comportamento. Se o trecho que nunca executa indica um erro de lógica (por exemplo, uma condição que deveria ser verdadeira em algum caso, ou um `return` antes da hora que pula uma etapa necessária), trate como bug, e não como esta regra.

### Como identificar

- Blocos de código comentado, em vez de removido.
- Imports, variáveis, parâmetros, métodos ou arquivos adicionados pelo PR que não são usados em lugar nenhum.
- Trechos depois de um `return`, `throw` ou `break` que nunca executam.
- Condições que nunca podem ser verdadeiras, quando o caso realmente não existe.

### Exceções

- Comentários que mostram um exemplo de uso ou explicam por que um trecho não deve ser feito de certa forma.
- Código ainda não usado que o próprio PR declara como preparação para uma próxima etapa. Na dúvida, reporte como dúvida.
- Parâmetros sem uso exigidos por uma interface, um callback ou uma assinatura de framework.

### Como sugerir

- Remover o código comentado: o histórico do Git já guarda a versão anterior.
- Remover o que não é usado, ou perguntar se faltou a parte que usaria aquele código.

**Incorreto:**

```php
public function calculateTotal(array $items): float
{
    // $total = array_sum(array_column($items, 'price'));
    $total = 0.0;
    foreach ($items as $item) {
        $total += $item['price'] * $item['quantity'];
    }

    return $total;
}
```

**Correto:**

```php
public function calculateTotal(array $items): float
{
    $total = 0.0;
    foreach ($items as $item) {
        $total += $item['price'] * $item['quantity'];
    }

    return $total;
}
```

**Incorreto:**

```js
import { formatDate, formatCurrency } from './formatters.js';

export function renderPrice(value) {
  return formatCurrency(value);
}
```

**Correto:**

```js
import { formatCurrency } from './formatters.js';

export function renderPrice(value) {
  return formatCurrency(value);
}
```
