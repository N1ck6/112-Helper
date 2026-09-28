from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.core.permissions import RoleCode  # noqa: E402
from app.core.security import hash_password, new_opaque_token, utcnow  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.models.enums import CardSource, LessonMode, LessonStatus, UserStatus  # noqa: E402
from app.models.training import Lesson, LessonParticipant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories.users import GroupRepository, RoleRepository, UserRepository  # noqa: E402

STUDENT_PREFIX = "load_student"
STUDENT_PASSWORD = "Load#2026"  # только для нагрузочного стенда
GROUP_CODE = "НАГР-01"
FIXTURE_PATH = Path("var") / "load_fixture.json"


async def prepare(count: int, cards: int) -> dict:
    async with session_scope() as session:
        users_repo = UserRepository(session)
        roles_repo = RoleRepository(session)
        groups_repo = GroupRepository(session)

        student_role = await roles_repo.by_code(str(RoleCode.STUDENT))
        teacher = await users_repo.by_username("teacher")
        if student_role is None or teacher is None:
            raise SystemExit("Сначала выполните python -m scripts.seed")

        usernames: list[str] = []
        students: list[User] = []
        for index in range(1, count + 1):
            username = f"{STUDENT_PREFIX}_{index:03d}"
            usernames.append(username)
            user = await users_repo.by_username(username)
            if user is None:
                user = User(
                    username=username,
                    full_name=f"Нагрузочный обучающийся №{index}",
                    email=f"{username}@dds112.local",
                    password_hash=hash_password(STUDENT_PASSWORD),
                    status=UserStatus.ACTIVE,
                    organization="Нагрузочный стенд",
                    password_changed_at=utcnow(),
                )
                user.roles = [student_role]
                session.add(user)
            students.append(user)
        await session.flush()

        group = await groups_repo.by_code(GROUP_CODE)
        if group is None:
            group = await groups_repo.create(
                code=GROUP_CODE,
                name="Группа нагрузочного тестирования",
                curator_id=teacher.id,
            )
        await groups_repo.add_members(group.id, [student.id for student in students])

        lesson = Lesson(
            title="Нагрузочное тестирование: действия с карточками",
            mode=LessonMode.CARD_ACTION,
            teacher_id=teacher.id,
            group_id=group.id,
            card_source=CardSource.GENERATED,
            time_limit_seconds=600,
            status=LessonStatus.RUNNING,
            started_at=utcnow(),
            success_criteria={"max_errors": settings.DEFAULT_MAX_ERRORS, "min_score": 70.0},
        )
        for student in students:
            lesson.participants.append(
                LessonParticipant(student_id=student.id, resume_token=new_opaque_token(24))
            )
        session.add(lesson)
        await session.flush()

        cards_total = await _ensure_cards(session, cards)

        fixture = {
            "lesson_id": str(lesson.id),
            "students": usernames,
            "password": STUDENT_PASSWORD,
            "cards": cards_total,
        }

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    return fixture


async def _ensure_cards(session, target: int) -> int:
    import sqlalchemy as sa

    from app.models.card import IncidentCard
    from app.models.enums import CardOrigin, CardStatus

    existing = (
        await session.execute(
            sa.select(IncidentCard).where(
                IncidentCard.status == CardStatus.READY,
                IncidentCard.origin == CardOrigin.GENERATED,
                IncidentCard.is_active.is_(True),
            )
        )
    ).scalars().all()
    if not existing:
        raise SystemExit("Нет готовых карточек: выполните python -m scripts.seed")
    if len(existing) >= target:
        return len(existing)

    samples = list(existing)
    for index in range(len(existing), target):
        sample = samples[index % len(samples)]
        session.add(
            IncidentCard(
                card_no=f"LOAD-{index + 1:05d}",
                title=f"{sample.title} (нагрузочный стенд №{index + 1})",
                template_id=sample.template_id,
                scenario_id=sample.scenario_id,
                category_id=sample.category_id,
                origin=CardOrigin.GENERATED,
                status=CardStatus.READY,
                difficulty=sample.difficulty,
                caller_profile=dict(sample.caller_profile or {}),
                payload=dict(sample.payload or {}),
                expected_payload=dict(sample.expected_payload or {}),
                notification_list=list(sample.notification_list or []),
                time_limit_seconds=sample.time_limit_seconds,
            )
        )
    await session.flush()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Подготовка стенда нагрузочного тестирования")
    parser.add_argument("--students", type=int, default=100, help="Число обучающихся (по умолчанию 100)")
    parser.add_argument(
        "--cards", type=int, default=600, help="Сколько карточек должно быть в базе (по умолчанию 600)"
    )
    args = parser.parse_args()

    setup_logging()
    fixture = asyncio.run(prepare(args.students, args.cards))
    print(f"Занятие: {fixture['lesson_id']}")
    print(f"Обучающихся: {len(fixture['students'])} (пароль {fixture['password']})")
    print(f"Карточек в базе: {fixture['cards']}")
    print(f"Параметры записаны в {FIXTURE_PATH}")
    print("\nЗапуск нагрузки:")
    print("    uvicorn app.main:app --workers 4")
    print("    locust -f locustfile.py --headless -u 100 -r 20 -t 2m --host http://localhost:8000")


if __name__ == "__main__":
    main()
