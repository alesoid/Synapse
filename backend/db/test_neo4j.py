"""
Тест Neo4j client — задача 13 мая.
Запуск: python -m backend.db.test_neo4j
Предварительно: docker compose up -d neo4j
"""

import sys
import logging
from backend.db.neo4j_client import Neo4jClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def test_neo4j_client():
    print("\n=== Тест Neo4j Client ===\n")

    with Neo4jClient() as client:

        # 1. Создать 3 узла Document
        print("1. Создание узлов Document...")
        doc1_id = client.create_node("Document", {
            "id": "doc-001",
            "title": "Регламент деплоя",
            "doc_type": "standard",
            "access_level": 2,
            "last_updated": "2026-01-15",
        })
        doc2_id = client.create_node("Document", {
            "id": "doc-002",
            "title": "Политика информационной безопасности",
            "doc_type": "policy",
            "access_level": 4,
            "last_updated": "2025-11-01",
        })
        proc1_id = client.create_node("Process", {
            "id": "proc-001",
            "name": "Деплой",
            "description": "Процесс выкатки изменений в production",
            "access_level": 2,
        })
        print(f"   ✓ Создано: {doc1_id}, {doc2_id}, {proc1_id}")

        # 2. Создать связи
        print("\n2. Создание связей...")
        client.create_relationship("doc-001", "proc-001", "REFERENCES")
        client.create_relationship("doc-002", "doc-001", "GOVERNS")
        print("   ✓ doc-001 -[REFERENCES]-> proc-001")
        print("   ✓ doc-002 -[GOVERNS]-> doc-001")

        # 3. Получить соседей
        print("\n3. Получение соседей doc-001 (access_level=3)...")
        neighbors = client.get_neighbors("doc-001", access_level=3, depth=2)
        print(f"   ✓ Найдено соседей: {len(neighbors)}")
        for n in neighbors:
            print(f"     - {n.get('label')}({n.get('id')}): {n.get('name') or n.get('id')}")

        # 4. Поиск по свойству
        print("\n4. Поиск Document по doc_type=standard (access_level=3)...")
        found = client.search_by_property("Document", "doc_type", "standard", access_level=3)
        print(f"   ✓ Найдено: {len(found)}")

        # 5. RBAC проверка — junior не должен видеть doc-002 (access_level=4)
        print("\n5. RBAC проверка (junior, access_level=1)...")
        found_junior = client.search_by_property("Document", "doc_type", "policy", access_level=1)
        assert len(found_junior) == 0, "RBAC нарушен: junior видит policy документы!"
        print("   ✓ Junior не видит документы access_level=4 — RBAC работает")

        # 6. Статистика графа
        print("\n6. Статистика графа...")
        stats = client.get_stats()
        print(f"   ✓ Узлов: {stats['nodes']}, Рёбер: {stats['edges']}")

        print("\n=== Все тесты прошли ✓ ===\n")


if __name__ == "__main__":
    try:
        test_neo4j_client()
    except Exception as e:
        print(f"\n✗ Тест упал: {e}")
        sys.exit(1)
