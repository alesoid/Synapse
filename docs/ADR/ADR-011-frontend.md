# ADR-011: Frontend — Vanilla JS SPA (Tailwind CSS)

**Статус:** Принято (обновлено)  
**Дата:** 11 мая 2026 → 29 мая 2026  
**Автор:** Алеся Мороз

---

## Scope

| Этап | Что реализовано | Статус |
|---|---|---|
| **MVP** | Vanilla JS SPA + Tailwind CSS CDN, смонтирован FastAPI на `/ui`; Explorer как таблицы узлов/рёбер + ссылка на Neo4j Browser | ✅ Реализовано (`frontend/index.html`) |
| **Scale** | React + TypeScript + react-force-graph; Mobile App; Slack/Teams bot | 🔜 Вне скоупа MVP |

---

## Контекст

Synapse требует веб-интерфейс для двух режимов: Q&A чат (все роли) и Explorer визуализация графа знаний (только Admin). Ключевые требования:

- Отображение ответов с анимацией (типографический эффект — слово за словом)
- Explorer: таблица узлов/рёбер + ссылка на Neo4j Browser для полной визуализации (FR-07)
- Смена роли пользователя для демо (dropdown без JWT)
- Быстрый старт без сборочного инструмента

---

## Решение

**Vanilla JS + Tailwind CSS CDN** — статический `frontend/index.html`, смонтирован FastAPI-роутом `/ui`. Никакого сборщика (Vite/Webpack) — файл открывается напрямую.

```javascript
// Q&A с typing-анимацией (слово за словом)
function typeText(el, text, speed = 20) {
    el.textContent = '';
    const words = text.split(' ');
    let i = 0;
    const timer = setInterval(() => {
        if (i < words.length) {
            el.textContent += (i > 0 ? ' ' : '') + words[i++];
        } else clearInterval(timer);
    }, speed);
}

// Explorer граф — таблица из GET /graph
const { nodes, edges } = await (await fetch('/graph', {
    headers: { 'X-User-Role': 'admin' }
})).json();
renderTable(nodes, edges); // HTML-таблица
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

**Плюсы Vanilla JS SPA:**
- Нулевые зависимости сборки — `index.html` открывается без npm/vite/webpack
- Tailwind CDN — стилизация без конфигурации
- Быстро итерировать: правки видны после F5, не нужен hot reload
- Нет transpile-шага — меньше точек отказа на demo-окружении

**Минусы:**
- Нет TypeScript — ошибки типов только в runtime
- Нет интерактивной force-graph визуализации (таблицы вместо D3-графа)
- Компонентный подход сложнее без фреймворка при росте кодовой базы

**Почему не React в MVP:**
- React требует сборочного окружения (Node.js, npm, Vite) — лишний источник проблем на gpu-demo
- react-force-graph — Should Have по FR-08, а не Must Have

---

## Последствия

- Frontend смонтирован FastAPI на `/ui` — не отдельный порт
- Dropdown смены роли передаёт `X-User-Role` заголовок при каждом запросе
- Explorer режим отображается только при `role === 'admin'` — проверка на фронте и на бэке (FR-09)
- `GET /graph` возвращает nodes/edges в JSON → рендерится HTML-таблицей
- Ссылка на Neo4j Browser (`http://localhost:7474`) доступна из Explorer для Admin (FR-07)
- Scale-этап: заменить на React + TypeScript + react-force-graph

---

## Compliance & Ethics

**Регуляторное соответствие:**
- React, TypeScript, Tailwind, react-force-graph — MIT лицензии, коммерческое использование без ограничений
- Frontend обращается только к внутреннему FastAPI — нет внешних API вызовов из браузера

**Этические риски и меры снижения:**
- Риск отображения закрытого контента через клиентскую фильтрацию (проверка роли только на фронте). Мера: RBAC применяется на бэке (Qdrant + Neo4j фильтры) — фронтенд-проверка декоративная, реальная защита на сервере
- Риск утечки роли пользователя через browser history или DevTools (заголовок `X-User-Role` виден). Мера: явно задокументировано как ограничение MVP; в Scale заменяется на JWT с httpOnly cookie
