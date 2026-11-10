---
title: Sem código de debug
severity: Importante
tags: debug, limpeza, segurança
---

## Sem código de debug

Código de debug é o que foi colocado para inspecionar ou testar algo durante o desenvolvimento e não deveria chegar ao merge. Diferente de código morto, ele pode afetar o comportamento: expor dados, poluir logs, interromper a execução, pular testes ou fixar um valor que só servia para o teste manual.

### Severidade

- **Importante** (padrão): interrupções de execução, testes focados ou desativados, flags e valores fixos de teste e saídas de debug que mostram dados sensíveis ou mudam o resultado (por exemplo, um `var_dump` que vai para a resposta da API).
- **Sugestão:** saídas de debug que não encerram nem alteram o processamento e não mostram dados sensíveis, como um `console.log` de uma variável comum no meio de uma função.

### Como identificar

- Saídas de debug: `console.log`, `console.debug`, `console.table`, `var_dump`, `print_r`, `dd()`, `dump()`, `print()` e similares usados para inspecionar valores.
- Interrupções de debug: `debugger;`, `breakpoint()`, `die()` ou `exit()` usados para parar a execução durante testes manuais.
- Testes focados ou desativados sem motivo: `.only`, `.skip`, `fit`, `xit`, `@skip` e equivalentes. Um `.only` faz os outros testes deixarem de rodar.
- Flags ou valores fixos de teste esquecidos (por exemplo, `if (true)`, `$debug = true`, um ID ou e-mail fixo usado para testar).

### Exceções

- Logs feitos pelo mecanismo de log do projeto, com nível adequado e sem dados sensíveis.
- Saída no terminal em scripts de linha de comando, quando essa é a função do script.
- Testes desativados com motivo explícito e referência ao que falta (por exemplo, um comentário apontando a tarefa que vai reativá-los).

### Como sugerir

- Remover a saída ou a interrupção de debug. Se a informação for útil em produção, trocar pelo mecanismo de log do projeto, com o nível certo.
- Remover a flag ou o valor fixo de teste e voltar ao fluxo real.
- Reativar o teste focado ou desativado, ou pedir o motivo quando não estiver claro.

**Incorreto:**

```php
public function calculateTotal(array $items): float
{
    var_dump($items);

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
it.only('calcula o desconto do pedido', () => {
  console.log('pedido', order);
  expect(applyDiscount(order)).toBe(90);
});
```

**Correto:**

```js
it('calcula o desconto do pedido', () => {
  expect(applyDiscount(order)).toBe(90);
});
```
