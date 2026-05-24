# ADR-011: Frontend — React + TypeScript + react-force-graph

**Статус:** Принято  
**Дата:** 11 мая 2026  
**Автор:** Алеся Мороз

---

## Scope

| Этап | Что реализовано | Статус |
|---|---|---|
| **MVP** | React + TypeScript + Tailwind, react-force-graph для Explorer, Q&A чат-интерфейс | ✅ Текущее решение |
| **Scale** | Mobile App (React Native), Slack/Teams bot как дополнительные каналы; React UI остаётся основным веб-каналом | 🔜 Вне скоупа MVP |

---

## Контекст

Synapse требует веб-интерфейс для двух режимов: Q&A чат (все роли) и Explorer визуализация графа знаний (только Admin). Ключевые требования:

- Streaming-отображение ответов (токены появляются по мере генерации)
- Интерактивная визуализация графа: узлы, рёбра, клик для просмотра деталей (FR-07, FR-08)
- Смена роли пользователя для демо (dropdown без JWT)
- Компонентный подход для поддерживаемости

---

## Решение

**React 18 + TypeScript + Tailwind CSS** для UI, **react-force-graph** для визуализации графа в Explorer режиме.

```typescript
// Streaming Q&A
const response = await fetch('/query', { method: 'POST', body: ... });
const reader = response.body?.getReader();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  setAnswer(prev => prev + decode(value));
}

// Explorer граф
<ForceGraph2D
  graphData={{ nodes, links }}
  onNodeClick={(node) => fetchNodeDetails(node.id)}
  nodeLabel="name"
/>
```

---

## Альтернативы рассмотрены

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| **Vue 3 + Vite** | Легче React, быстрый старт, хорошая документация | Меньше готовых компонентов для graph visualization, меньше интеграций | **Отклонён** |
| **Next.js (SSR)** | SEO, серверный рендеринг, файловый роутинг | SSR избыточен для внутреннего корпоративного инструмента без SEO-требований | **Отклонён** |
| **D3.js напрямую** | Максимальная гибкость визуализации графа | Высокие трудозатраты на реализацию интерактивности (zoom, drag, click) с нуля | **Отклонён** |
| **Neo4j Bloom / Neo4j Browser** | Встроенная визуализация Neo4j, нет разработки | Отдельный инструмент вне основного UI, нет интеграции с RBAC и Q&A режимом | **Отклонён** |
| **Grafana (для графа)** | Уже есть в стеке | Grafana — для метрик, не для интерактивной визуализации property graph | **Отклонён** |
| **Streamlit / Gradio** | Быстрый прототип, минимум кода | Ограниченная кастомизация UI, не подходит для production-вида демо | **Отклонён** |

---

## Trade-offs

**Плюсы React + react-force-graph:**
- React — de facto стандарт для корпоративных веб-приложений, богатая экосистема
- TypeScript — типизация предотвращает ошибки при работе с API-ответами (AgentState, GraphData)
- Tailwind — быстрая стилизация без написания CSS с нуля
- react-force-graph — обёртка над D3 force simulation: интерактивность (zoom, drag, click) из коробки, 2D и 3D режимы

**Минусы:**
- React + TypeScript — выше порог входа по сравнению с Vue или Streamlit
- react-force-graph плохо масштабируется на больших графах (>1000 узлов) — для MVP (50-100 узлов) достаточно
- Tailwind генерирует большой CSS bundle без purge (настраивается в build)

---

## Последствия

- Frontend запускается на порту 3000 в Docker Compose
- Dropdown смены роли передаёт `X-User-Role` заголовок при каждом запросе
- Explorer режим отображается только при `role === 'admin'` — проверка на фронте и на бэке (FR-09)
- `react-force-graph` получает данные из `GET /graph` — только узлы и рёбра доступные Admin (access_level=5)

---

## Compliance & Ethics

**Регуляторное соответствие:**
- React, TypeScript, Tailwind, react-force-graph — MIT лицензии, коммерческое использование без ограничений
- Frontend обращается только к внутреннему FastAPI — нет внешних API вызовов из браузера

**Этические риски и меры снижения:**
- Риск отображения закрытого контента через клиентскую фильтрацию (проверка роли только на фронте). Мера: RBAC применяется на бэке (Qdrant + Neo4j фильтры) — фронтенд-проверка декоративная, реальная защита на сервере
- Риск утечки роли пользователя через browser history или DevTools (заголовок `X-User-Role` виден). Мера: явно задокументировано как ограничение MVP; в Scale заменяется на JWT с httpOnly cookie
