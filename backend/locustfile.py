from __future__ import annotations

import itertools
import json
from pathlib import Path

from locust import HttpUser, between, events, task

FIXTURE_PATH = Path("var") / "load_fixture.json"

#: Цепочка статусов одной карточки по памятке «Работа на АРМ-112».
RESPONSE_CHAIN = [
    ("accepted", "Карточка принята, наряд формируется"),
    ("response_started", "Подразделение направлено к месту происшествия"),
    ("arrived", "Прибытие подразделения на место"),
    ("work_in_progress", "Проводятся работы по происшествию"),
    ("work_completed", "Работы завершены, информация передана в диспетчерскую"),
]


def _load_fixture() -> dict:
    if not FIXTURE_PATH.exists():
        raise RuntimeError(
            "Не найден var/load_fixture.json — выполните python -m scripts.load_setup"
        )
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


FIXTURE = _load_fixture()
_ACCOUNTS = itertools.cycle(FIXTURE["students"])

#: Счётчики для итогового отчёта: сколько карточек закрыто и сколько записей сделано.
STATS = {"cards_closed": 0, "writes": 0}


class DispatcherUser(HttpUser):
    """Один виртуальный диспетчер ДДС на своём рабочем месте."""

    #: Пауза между карточками — оператор не работает в режиме бенчмарка.
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        self.username = next(_ACCOUNTS)
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": FIXTURE["password"]},
            name="POST /auth/login",
        )
        if response.status_code != 200:
            self.environment.runner.quit()
            raise RuntimeError(f"Вход не выполнен: {response.text[:200]}")
        self.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        self.lesson_id = FIXTURE["lesson_id"]
        self.client.post(
            f"/api/v1/training/lessons/{self.lesson_id}/join",
            headers=self.headers,
            name="POST /training/lessons/{id}/join",
        )

    @task(10)
    def process_card(self) -> None:
        """Полный цикл работы с карточкой — основной источник записи в БД."""
        issued = self.client.post(
            f"/api/v1/training/lessons/{self.lesson_id}/next-card",
            headers=self.headers,
            name="POST /training/lessons/{id}/next-card",
        )
        if issued.status_code != 200:
            return
        attempt_id = issued.json()["attempt"]["id"]

        for status_code, comment in RESPONSE_CHAIN:
            response = self.client.post(
                f"/api/v1/training/attempts/{attempt_id}/response-status",
                headers=self.headers,
                json={"status": status_code, "comment": comment},
                name="POST /training/attempts/{id}/response-status",
            )
            if response.status_code != 201:
                return
            STATS["writes"] += 1
        STATS["cards_closed"] += 1

    @task(3)
    def read_options(self) -> None:
        """Чтение доступных статусов — самый частый запрос на АРМ-112."""
        self.client.get("/api/v1/auth/me", headers=self.headers, name="GET /auth/me")

    @task(1)
    def read_own_results(self) -> None:
        self.client.get(
            "/api/v1/evaluations/my",
            headers=self.headers,
            params={"size": 10},
            name="GET /evaluations/my",
        )


@events.quitting.add_listener
def _report(environment, **_kwargs) -> None:
    stats = environment.stats.total
    duration = max(1.0, (stats.last_request_timestamp or 0) - (stats.start_time or 0))
    p95 = stats.get_response_time_percentile(0.95)

    print("\n=== Требования п.2.8 ТЗ ===")
    print(f"  Запросов всего:          {stats.num_requests}")
    print(f"  Ошибок:                  {stats.num_failures}")
    print(f"  Медиана отклика:         {stats.median_response_time} мс")
    print(f"  95-й процентиль (все):   {p95:.0f} мс (норматив ≤ 2000 мс)")
    print(f"  Пропускная способность:  {stats.total_rps:.1f} запросов/с")
    print(f"  Карточек закрыто:        {STATS['cards_closed']}")
    print(f"  Операций записи:         {STATS['writes'] / duration:.1f} в секунду (норматив ≥ 100)")

    print("\n  Рабочие операции (без входа и присоединения):")
    for key, entry in environment.stats.entries.items():
        name = key[0] if isinstance(key, tuple) else key
        if "login" in name or "join" in name:
            continue
        print(
            f"    {name:<52} медиана {entry.median_response_time:>5} мс, "
            f"95% {entry.get_response_time_percentile(0.95):>5.0f} мс, "
            f"{entry.num_requests} запросов"
        )
