"""Отчётность, экспорт и сертификаты (п.2.6)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, PageDep, SessionDep, require
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.schemas.report import (
    CertificateIssueRequest,
    CertificateRead,
    ReportCreate,
    ReportRead,
)
from app.services.reports import ReportService

router = APIRouter(tags=["Отчётность"])


@router.get("/reports", response_model=Page[ReportRead], summary="Список отчётов")
async def list_reports(session: SessionDep, page: PageDep, user: CurrentUser) -> Page[ReportRead]:
    own_only = not user.has_permission(Perm.REPORTS_READ)
    items, total = await ReportService(session).list_reports(user, page, own_only=own_only)
    return build_page([ReportRead.model_validate(item) for item in items], total, page)


@router.post(
    "/reports",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
    summary="Сформировать отчёт",
    description=(
        "Типы: lesson (отчёт о занятии с действиями, замечаниями, временем и грамматикой), "
        "progress (успеваемость обучающегося с прогнозом), group_stats, errors, timing. "
        "Форматы: json / csv / pdf."
    ),
)
async def create_report(
    data: ReportCreate,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.REPORTS_READ)),
) -> ReportRead:
    report = await ReportService(session).create(data, actor, request)
    return ReportRead.model_validate(report)


@router.get("/reports/{report_id}", response_model=ReportRead, summary="Отчёт")
async def get_report(
    report_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.REPORTS_READ))
) -> ReportRead:
    return ReportRead.model_validate(await ReportService(session).get(report_id))


@router.get(
    "/reports/{report_id}/download",
    summary="Скачать файл отчёта (CSV/PDF)",
)
async def download_report(
    report_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.REPORTS_EXPORT))
) -> FileResponse:
    service = ReportService(session)
    report = await service.get(report_id)
    path = await service.file_path(report_id)
    return FileResponse(path, filename=path.name, media_type=_media_type(report.format.value))


@router.post(
    "/certificates",
    response_model=CertificateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Выдать сертификат о прохождении обучения",
)
async def issue_certificate(
    data: CertificateIssueRequest,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.CERTIFICATES_ISSUE)),
) -> CertificateRead:
    certificate = await ReportService(session).issue_certificate(data, actor, request)
    return CertificateRead.model_validate(certificate)


@router.get("/certificates", response_model=Page[CertificateRead], summary="Выданные сертификаты")
async def list_certificates(
    session: SessionDep, page: PageDep, user: CurrentUser
) -> Page[CertificateRead]:
    student_id = None if user.has_permission(Perm.CERTIFICATES_ISSUE) else user.id
    items, total = await ReportService(session).list_certificates(page, student_id=student_id)
    return build_page([CertificateRead.model_validate(item) for item in items], total, page)


@router.get("/certificates/{certificate_id}/download", summary="Скачать сертификат (PDF)")
async def download_certificate(
    certificate_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> FileResponse:
    certificate, path = await ReportService(session).certificate_file(certificate_id, user)
    return FileResponse(
        path, filename=f"certificate_{certificate.serial.replace('/', '_')}.pdf", media_type="application/pdf"
    )


def _media_type(fmt: str) -> str:
    return {
        "csv": "text/csv; charset=utf-8",
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(fmt, "application/octet-stream")
