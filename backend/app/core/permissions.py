from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class Perm(StrEnum):
    # --- пользователи и доступ
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_BLOCK = "users:block"
    ROLES_MANAGE = "roles:manage"
    GROUPS_READ = "groups:read"
    GROUPS_MANAGE = "groups:manage"
    GROUPS_ASSIGN = "groups:assign"

    # --- системные функции администратора
    SYSTEM_SERVICES = "system:services"
    SYSTEM_CONFIG = "system:config"
    SYSTEM_BACKUP = "system:backup"
    SYSTEM_LOGS = "system:logs"
    SYSTEM_MONITOR = "system:monitor"
    AUDIT_READ = "audit:read"

    # --- учебный контент
    CATALOG_READ = "catalog:read"
    CATALOG_WRITE = "catalog:write"
    SCENARIOS_READ = "scenarios:read"
    SCENARIOS_WRITE = "scenarios:write"
    SCENARIOS_APPROVE = "scenarios:approve"
    SCENARIOS_GENERATE = "scenarios:generate"
    MATERIALS_READ = "materials:read"
    MATERIALS_WRITE = "materials:write"
    CARDS_READ = "cards:read"
    CARDS_WRITE = "cards:write"

    # --- занятия
    LESSONS_MANAGE = "lessons:manage"
    LESSONS_MONITOR = "lessons:monitor"
    LESSONS_PARTICIPATE = "lessons:participate"

    # --- оценки, аналитика, отчёты
    EVALUATIONS_READ = "evaluations:read"
    EVALUATIONS_READ_OWN = "evaluations:read_own"
    EVALUATIONS_OVERRIDE = "evaluations:override"
    RECOMMENDATIONS_READ = "recommendations:read"
    RECOMMENDATIONS_READ_OWN = "recommendations:read_own"
    REPORTS_READ = "reports:read"
    REPORTS_READ_OWN = "reports:read_own"
    REPORTS_EXPORT = "reports:export"
    CERTIFICATES_ISSUE = "certificates:issue"
    CERTIFICATES_READ_OWN = "certificates:read_own"

    # --- телефония
    TELEPHONY_MANAGE = "telephony:manage"
    TELEPHONY_USE = "telephony:use"


#: Человекочитаемый каталог прав (наполняет таблицу ``permissions`` при seed/миграции).
PERMISSION_CATALOG: dict[Perm, tuple[str, str]] = {
    Perm.USERS_READ: ("Просмотр пользователей", "Пользователи"),
    Perm.USERS_WRITE: ("Создание и изменение пользователей", "Пользователи"),
    Perm.USERS_BLOCK: ("Блокировка учётных записей", "Пользователи"),
    Perm.ROLES_MANAGE: ("Управление ролями и правами", "Пользователи"),
    Perm.GROUPS_READ: ("Просмотр учебных групп", "Пользователи"),
    Perm.GROUPS_MANAGE: ("Управление учебными группами", "Пользователи"),
    Perm.GROUPS_ASSIGN: ("Назначение обучающихся в группы", "Пользователи"),
    Perm.SYSTEM_SERVICES: ("Запуск и остановка сервисов", "Система"),
    Perm.SYSTEM_CONFIG: ("Изменение конфигурации системы", "Система"),
    Perm.SYSTEM_BACKUP: ("Резервное копирование", "Система"),
    Perm.SYSTEM_LOGS: ("Просмотр системных журналов", "Система"),
    Perm.SYSTEM_MONITOR: ("Мониторинг состояния и нагрузки", "Система"),
    Perm.AUDIT_READ: ("Просмотр журнала аудита", "Система"),
    Perm.CATALOG_READ: ("Просмотр классификатора происшествий", "Контент"),
    Perm.CATALOG_WRITE: ("Изменение классификатора происшествий", "Контент"),
    Perm.SCENARIOS_READ: ("Просмотр учебных сценариев", "Контент"),
    Perm.SCENARIOS_WRITE: ("Создание и изменение сценариев", "Контент"),
    Perm.SCENARIOS_APPROVE: ("Утверждение сценариев и эталонов", "Контент"),
    Perm.SCENARIOS_GENERATE: ("Генерация сценариев нейросетью", "Контент"),
    Perm.MATERIALS_READ: ("Просмотр методических материалов", "Контент"),
    Perm.MATERIALS_WRITE: ("Загрузка методических материалов", "Контент"),
    Perm.CARDS_READ: ("Просмотр карточек происшествий", "Контент"),
    Perm.CARDS_WRITE: ("Создание и изменение карточек", "Контент"),
    Perm.LESSONS_MANAGE: ("Управление занятиями", "Занятия"),
    Perm.LESSONS_MONITOR: ("Мониторинг занятий в реальном времени", "Занятия"),
    Perm.LESSONS_PARTICIPATE: ("Участие в занятии как обучающийся", "Занятия"),
    Perm.EVALUATIONS_READ: ("Просмотр оценок обучающихся", "Оценки"),
    Perm.EVALUATIONS_READ_OWN: ("Просмотр собственных оценок", "Оценки"),
    Perm.EVALUATIONS_OVERRIDE: ("Корректировка оценки (экспертная)", "Оценки"),
    Perm.RECOMMENDATIONS_READ: ("Просмотр рекомендаций ИИ по группе", "Аналитика"),
    Perm.RECOMMENDATIONS_READ_OWN: ("Просмотр собственных рекомендаций", "Аналитика"),
    Perm.REPORTS_READ: ("Просмотр отчётов", "Отчётность"),
    Perm.REPORTS_READ_OWN: ("Просмотр собственных отчётов", "Отчётность"),
    Perm.REPORTS_EXPORT: ("Экспорт отчётов (CSV/PDF/XLSX)", "Отчётность"),
    Perm.CERTIFICATES_ISSUE: ("Выдача сертификатов", "Отчётность"),
    Perm.CERTIFICATES_READ_OWN: ("Получение собственного сертификата", "Отчётность"),
    Perm.TELEPHONY_MANAGE: ("Настройка IP-телефонии", "Телефония"),
    Perm.TELEPHONY_USE: ("Приём учебных вызовов", "Телефония"),
}

ADMIN_PERMISSIONS: set[Perm] = {
    Perm.USERS_READ, Perm.USERS_WRITE, Perm.USERS_BLOCK, Perm.ROLES_MANAGE,
    Perm.GROUPS_READ, Perm.GROUPS_MANAGE,
    Perm.SYSTEM_SERVICES, Perm.SYSTEM_CONFIG, Perm.SYSTEM_BACKUP, Perm.SYSTEM_LOGS,
    Perm.SYSTEM_MONITOR, Perm.AUDIT_READ,
    #: классификатор и справочные материалы — для администрирования данных; сценарии, карточки
    #: с эталонами и оценки — учебный контент преподавателя (п.2 ТЗ: минимальные привилегии)
    Perm.CATALOG_READ, Perm.MATERIALS_READ,
    Perm.TELEPHONY_MANAGE,
}

TEACHER_PERMISSIONS: set[Perm] = {
    Perm.USERS_READ, Perm.GROUPS_READ, Perm.GROUPS_ASSIGN,
    Perm.CATALOG_READ, Perm.CATALOG_WRITE,
    Perm.SCENARIOS_READ, Perm.SCENARIOS_WRITE, Perm.SCENARIOS_APPROVE, Perm.SCENARIOS_GENERATE,
    Perm.MATERIALS_READ, Perm.MATERIALS_WRITE,
    Perm.CARDS_READ, Perm.CARDS_WRITE,
    Perm.LESSONS_MANAGE, Perm.LESSONS_MONITOR,
    Perm.EVALUATIONS_READ, Perm.EVALUATIONS_OVERRIDE,
    Perm.RECOMMENDATIONS_READ,
    Perm.REPORTS_READ, Perm.REPORTS_EXPORT, Perm.CERTIFICATES_ISSUE,
    Perm.TELEPHONY_USE,
}

#: Обучающийся не читает сценарии и карточки напрямую: там эталон и то, что оператор 112 должен
#: выяснить у заявителя. Свою карточку он получает только через /training — с правилами видимости.
STUDENT_PERMISSIONS: set[Perm] = {
    Perm.LESSONS_PARTICIPATE,
    Perm.MATERIALS_READ, Perm.CATALOG_READ,
    Perm.EVALUATIONS_READ_OWN, Perm.RECOMMENDATIONS_READ_OWN,
    Perm.REPORTS_READ_OWN, Perm.CERTIFICATES_READ_OWN,
    Perm.TELEPHONY_USE,
}

DEFAULT_ROLE_PERMISSIONS: dict[RoleCode, set[Perm]] = {
    RoleCode.ADMIN: ADMIN_PERMISSIONS,
    RoleCode.TEACHER: TEACHER_PERMISSIONS,
    RoleCode.STUDENT: STUDENT_PERMISSIONS,
}

ROLE_TITLES: dict[RoleCode, str] = {
    RoleCode.ADMIN: "Администратор системы",
    RoleCode.TEACHER: "Преподаватель",
    RoleCode.STUDENT: "Обучающийся",
}
