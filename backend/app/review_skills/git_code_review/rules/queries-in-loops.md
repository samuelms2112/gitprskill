---
title: Sem consultas dentro de loops
severity: Importante
tags: performance, banco de dados, integrações
---

## Sem consultas dentro de loops

Fazer uma consulta ao banco ou uma chamada HTTP para cada item de uma lista multiplica o custo pelo tamanho da lista. Com poucos itens o código parece correto; com volume real, a tela fica lenta, a requisição estoura o tempo limite ou a API externa começa a recusar chamadas. É o problema conhecido como N+1: uma consulta para buscar a lista e mais uma para cada item.

### Como identificar

- Chamadas a repositórios, models, queries SQL ou métodos que acessam o banco dentro de `foreach`, `for`, `while`, `map`, `forEach` ou similares.
- Acesso a relacionamentos de ORM dentro de um loop sem carregamento antecipado (eager loading), quando cada acesso dispara uma consulta.
- Chamadas HTTP, a filas ou a serviços externos feitas item por item.
- Inserções, atualizações ou exclusões feitas uma a uma dentro do loop, quando poderiam ser feitas em lote.
- `await` dentro de um loop que executa chamadas independentes em sequência, uma esperando a outra.
- Métodos chamados no loop que, por dentro, fazem uma consulta. Confira a implementação antes de concluir.

### Exceções

- Loops com quantidade pequena e fixa de itens, conhecida de antemão (por exemplo, uma lista de três tipos configurados).
- Processamento que já é feito em lotes (paginado ou em blocos), em que cada consulta trata vários itens.
- Casos em que cada chamada depende do resultado da anterior e não pode ser agrupada.
- Rotinas em segundo plano que processam item a item de propósito, por limite de taxa da API externa ou para isolar falhas. Na dúvida, reporte como dúvida.

### Como sugerir

- Buscar todos os dados de uma vez antes do loop (por exemplo, com `WHERE id IN (...)` ou um `JOIN`) e montar um mapa por ID para consulta dentro do loop.
- Usar o carregamento antecipado do ORM quando o projeto usar um.
- Fazer inserções e atualizações em lote.
- Para chamadas HTTP independentes, usar um endpoint que aceite vários itens, quando existir, ou executar as chamadas em paralelo com um limite de concorrência.
- Indicar no comentário o efeito com volume real (por exemplo, "com 500 pedidos são 501 consultas"), para deixar claro por que vale corrigir.

**Incorreto:**

```php
$orders = $this->orderRepository->findByCustomer($customerId);

foreach ($orders as $order) {
    $order->product = $this->productRepository->findById($order->productId);
}
```

**Correto:**

```php
$orders = $this->orderRepository->findByCustomer($customerId);
$productIds = array_unique(array_column($orders, 'productId'));
$productsById = $this->productRepository->findByIds($productIds);

foreach ($orders as $order) {
    $order->product = $productsById[$order->productId] ?? null;
}
```

**Incorreto:**

```js
const results = [];
for (const id of userIds) {
  results.push(await fetchUser(id));
}
```

**Correto:**

```js
const results = await fetchUsersByIds(userIds);
```
