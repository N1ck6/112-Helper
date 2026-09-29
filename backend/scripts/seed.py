from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.arm112 import EKP_MATRIX, REQUIRED_CARD_FIELDS  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.core.permissions import (  # noqa: E402
    DEFAULT_ROLE_PERMISSIONS,
    PERMISSION_CATALOG,
    ROLE_TITLES,
    RoleCode,
)
from app.core.security import hash_password, utcnow  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.models.catalog import DutyService, TimeNorm  # noqa: E402
from app.models.enums import (  # noqa: E402
    DifficultyLevel,
    ScenarioStatus,
    ServiceLevel,
    UserStatus,
)
from app.models.training import Workplace  # noqa: E402
from app.models.user import Permission, Role, StudyGroup, User  # noqa: E402
from app.repositories.content import CategoryRepository, ScenarioRepository  # noqa: E402
from app.repositories.users import GroupRepository, RoleRepository, UserRepository  # noqa: E402
from app.schemas.scenario import GenerateScenariosRequest, ScenarioApproveRequest  # noqa: E402
from app.services.cards import CardService  # noqa: E402
from app.services.scenarios import ScenarioService  # noqa: E402

#: Стартовые учётные записи. Пароли — из корневого .env (установщик генерирует случайные);
#: значения по умолчанию — только для автотестов и разработки без Docker.
#: Пароль задаётся при создании записи; дальше его меняет сам пользователь или администратор.
DEMO_USERS = [
    ("admin", "Администратов Артём Сергеевич", RoleCode.ADMIN, os.getenv("ADMIN_PASSWORD") or "Admin#2026"),
    ("teacher", "Преподавалова Мария Ивановна", RoleCode.TEACHER, os.getenv("TEACHER_PASSWORD") or "Teacher#2026"),
    ("student", "Учащихся Дмитрий Олегович", RoleCode.STUDENT, os.getenv("STUDENT_PASSWORD") or "Student#2026"),
    ("student2", "Смирнова Елена Павловна", RoleCode.STUDENT, os.getenv("STUDENT_PASSWORD") or "Student#2026"),
]

CATEGORIES = [
    ("traffic_accident", "Дорожно-транспортные происшествия", None, "ДПС ГИБДД", []),
    ("traffic_injured", "ДТП с пострадавшими", "traffic_accident", "ДПС ГИБДД", ["victims_count"]),
    ("fire", "Пожары и загорания", None, "Пожарно-спасательный гарнизон", []),
    ("fire_apartment", "Пожар в жилом помещении", "fire", "Пожарно-спасательный гарнизон",
     ["address_flat", "address_entrance", "address_floor"]),
    ("fire_transport", "Загорание транспортного средства", "fire", "Пожарно-спасательный гарнизон", []),
    ("medical", "Медицинская помощь", None, "Скорая медицинская помощь", ["victims_count"]),
    ("utilities", "ЖКХ и коммунальные аварии", None, "АО «Мосводоканал»", []),
    ("utilities_water", "Авария водоснабжения", "utilities", "АО «Мосводоканал»", []),
    ("heating", "Авария теплоснабжения", "utilities", "ПАО «МОЭК»", []),
    ("gas", "Происшествия с газом", None, "Аварийная газовая служба", []),
    ("public_order", "Нарушения общественного порядка", None, "Полиция", []),
]

WORKPLACES = [
    (f"{number:02d}", f"АРМ-112 № {number:02d}", "Учебный класс 1", f"11{number:02d}")
    for number in range(1, 11)
]

DUTY_SERVICES = [
    ("101", "Пожарно-спасательный гарнизон", "emergency", None, None, None, "101", [], True),
    ("102", "Полиция", "emergency", None, None, None, "102", [], True),
    ("103", "Скорая медицинская помощь", "emergency", None, None, None, "103", [], True),
    ("104", "Аварийная газовая служба", "emergency", None, None, None, "104", [], True),
    ("dds_szao", "ДДС Северо-Западного административного округа", "okrug",
     "СЗАО", None, None, "2100", [], False),
    ("dds_uzao", "ДДС Юго-Западного административного округа", "okrug",
     "ЮЗАО", None, None, "2200", [], False),
    ("dds_shchukino", "ДДС управы района Щукино", "district",
     "СЗАО", "Щукино", "dds_szao", "2101", [], False),
    ("dds_akademichesky", "ДДС управы Академического района", "district",
     "ЮЗАО", "Академический", "dds_uzao", "2201", [], False),
    ("dds_education", "ДДС Департамента образования города Москвы", "department",
     None, None, None, "2300", ["fire", "fire_apartment", "medical"], False),
]


async def seed_permissions_and_roles(session) -> dict[str, Role]:
    perm_repo = RoleRepository(session)
    existing_perms = {
        perm.code: perm
        for perm in (await session.execute(__import__("sqlalchemy").select(Permission))).scalars().all()
    }
    for code, (name, category) in PERMISSION_CATALOG.items():
        if str(code) not in existing_perms:
            perm = Permission(code=str(code), name=name, category=category)
            session.add(perm)
            existing_perms[str(code)] = perm
    await session.flush()

    roles: dict[str, Role] = {}
    for role_code, perms in DEFAULT_ROLE_PERMISSIONS.items():
        role = await perm_repo.by_code(str(role_code))
        if role is None:
            role = Role(code=str(role_code), name=ROLE_TITLES[role_code], is_system=True)
            session.add(role)
        role.name = ROLE_TITLES[role_code]
        role.is_system = True
        role.permissions = [existing_perms[str(p)] for p in perms]
        roles[str(role_code)] = role
    await session.flush()
    print(f"  ✓ прав: {len(existing_perms)}, ролей: {len(roles)}")
    return roles


async def seed_users(session, roles: dict[str, Role]) -> dict[str, User]:
    repo = UserRepository(session)
    users: dict[str, User] = {}
    for username, full_name, role_code, password in DEMO_USERS:
        user = await repo.by_username(username)
        if user is None:
            user = User(
                username=username,
                full_name=full_name,
                email=f"{username}@dds112.local",
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
                organization="ГБУ «Система 112»",
                password_changed_at=utcnow(),
            )
            session.add(user)
        user.roles = [roles[str(role_code)]]
        users[username] = user
    await session.flush()
    print(f"  ✓ пользователей: {len(users)} (пароли см. в scripts/seed.py)")
    return users


async def seed_catalog(session) -> dict[str, object]:
    repo = CategoryRepository(session)
    categories = {}
    for code, name, parent_code, profile, extra_required in CATEGORIES:
        parent = categories.get(parent_code) if parent_code else None
        notify = [
            {"code": service_code, "is_primary": is_primary, "reason": "ЕКП"}
            for service_code, is_primary in EKP_MATRIX.get(code, [])
        ]
        required = list(REQUIRED_CARD_FIELDS) + extra_required
        category = await repo.by_code(code)
        if category is None:
            category = await repo.create(
                code=code,
                name=name,
                parent_id=parent.id if parent else None,
                dds_profile=profile,
                required_fields=required,
                notify_services=notify,
                default_difficulty=DifficultyLevel.BASIC,
            )
        else:
            category.parent_id = parent.id if parent else None
            category.required_fields = required
            category.notify_services = notify
        categories[code] = category
    await session.flush()

    import sqlalchemy as sa

    has_default_norm = (
        await session.execute(
            sa.select(TimeNorm).where(TimeNorm.category_id.is_(None), TimeNorm.mode.is_(None))
        )
    ).scalars().first()
    if has_default_norm is None:
        session.add(TimeNorm(seconds=30, comment="Норматив по умолчанию согласно ТЗ"))
    await session.flush()
    print(f"  ✓ категорий: {len(categories)}, норматив по умолчанию: 30 с")
    return categories


async def seed_workplaces(session) -> int:
    """Рабочие места учебного класса: по их номерам раздаются задания."""
    import sqlalchemy as sa

    existing = {
        row.number
        for row in (await session.execute(sa.select(Workplace.number))).all()
    }
    created = 0
    for number, title, room, extension in WORKPLACES:
        if number in existing:
            continue
        session.add(
            Workplace(number=number, title=title, room=room, phone_extension=extension)
        )
        created += 1
    await session.flush()
    print(f"  рабочие места: {created} создано, {len(existing)} уже было")
    return created


async def seed_duty_services(session) -> int:
    """Справочник ДДС: по нему карточка расходится по району и подчинённости."""
    import sqlalchemy as sa

    existing = {
        row.code: row.id
        for row in (await session.execute(sa.select(DutyService.code, DutyService.id))).all()
    }
    created = 0
    for code, name, level, okrug, area, _parent, extension, categories, primary in DUTY_SERVICES:
        if code in existing:
            continue
        service = DutyService(
            code=code,
            name=name,
            level=ServiceLevel(level),
            okrug=okrug,
            area=area,
            phone_extension=extension,
            categories=categories,
            is_primary=primary,
            supervisor={
                "position": "Старший оперативный дежурный",
                "phone": extension,
            },
        )
        session.add(service)
        created += 1
    await session.flush()

    codes = {
        row.code: row.id
        for row in (await session.execute(sa.select(DutyService.code, DutyService.id))).all()
    }
    for code, _n, _l, _o, _a, parent_code, *_rest in DUTY_SERVICES:
        if not parent_code:
            continue
        service = await session.get(DutyService, codes[code])
        if service is not None and service.parent_id is None:
            service.parent_id = codes.get(parent_code)
    await session.flush()
    print(f"  справочник ДДС: {created} служб создано, всего {len(codes)}")
    return created


async def seed_group(session, users: dict[str, User]) -> StudyGroup:
    repo = GroupRepository(session)
    group = await repo.by_code("ДДС-01")
    if group is None:
        group = await repo.create(
            code="ДДС-01",
            name="Учебная группа операторов ДДС №1",
            dds_profile="ГБУ «Система 112»",
            curator_id=users["teacher"].id,
        )
    student_ids = [users["student"].id, users["student2"].id]
    await repo.add_members(group.id, student_ids)
    print("  ✓ группа ДДС-01 с двумя обучающимися")
    return group


async def seed_incident_classifier(session) -> int:
    """Классификатор происшествий заказчика (Klassifikator.xlsx) — в таблицу incident_types.

    Путь — CLASSIFIER_XLSX (в полном стенде смонтирована ml/data/raw). Уже загружен или файла
    нет — пропуск: классификатор можно загрузить позже через POST /incidents/import/xlsx.
    """
    import os

    from app.services.incidents import IncidentCatalogService

    path = Path(os.environ.get("CLASSIFIER_XLSX", ""))
    service = IncidentCatalogService(session)
    if await service.types.count() > 0:
        print("  • классификатор происшествий уже загружен — пропускаю")
        return 0
    if not path.is_file():
        print("  • классификатор происшествий: файл не задан (CLASSIFIER_XLSX) — пропускаю")
        return 0
    items = service.parse_xlsx(path.read_bytes())
    result = await service.import_types(items)
    print(f"  ✓ классификатор происшествий: {result['imported']} типов из {path.name}")
    return result["imported"]


async def seed_scenarios(session, users: dict[str, User], categories: dict) -> int:
    scenario_repo = ScenarioRepository(session)
    approved = await scenario_repo.count(ScenarioRepository.model.status == ScenarioStatus.APPROVED)
    if approved:
        print(f"  • сценарии уже есть (утверждённых: {approved}) — пропускаю")
        return approved

    await CardService(session).ensure_default_template()
    service = ScenarioService(session)
    teacher = users["teacher"]
    created = 0
    for code in ("traffic_injured", "fire_apartment", "medical", "utilities_water"):
        scenarios = await service.generate(
            GenerateScenariosRequest(
                category_id=categories[code].id, difficulty=DifficultyLevel.BASIC, count=3, with_cards=True
            ),
            teacher,
        )
        for scenario in scenarios:
            await service.approve(scenario.id, ScenarioApproveRequest(comment="Утверждено при установке"), teacher)
            created += 1
    print(f"  ✓ сценариев с утверждёнными эталонами и карточками: {created}")
    return created


async def reset_schema() -> None:
    import sqlalchemy as sa

    from app.db.session import engine

    async with engine.begin() as connection:
        await connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        await connection.execute(sa.text("CREATE SCHEMA public"))
    await engine.dispose()
    print("  ✓ схема очищена")


def upgrade_to_head() -> None:
    """Накатывает миграции — тот же путь, что и в эксплуатации (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    print("  ✓ миграции применены")


async def main() -> None:
    setup_logging()
    print("Наполнение базы стартовыми данными…")
    async with session_scope() as session:
        roles = await seed_permissions_and_roles(session)
        users = await seed_users(session, roles)
        categories = await seed_catalog(session)
        await seed_workplaces(session)
        await seed_duty_services(session)
        await seed_group(session, users)
        await seed_incident_classifier(session)
        await seed_scenarios(session, users, categories)
    print("\nГотово. Учётные записи для входа (пароли — в корневом .env):")
    for username, _, role, _password in DEMO_USERS:
        print(f"  {username:9} — {ROLE_TITLES[role]}")
    print("\nПроверить API: http://localhost:8000/docs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Стартовые данные тренажёра ДДС-112")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="пересоздать схему: удалить таблицы, накатить миграции и заполнить заново",
    )
    arguments = parser.parse_args()

    if arguments.reset:
        print("Пересоздание схемы (все учебные данные будут удалены)…")
        asyncio.run(reset_schema())
        upgrade_to_head()

    asyncio.run(main())
