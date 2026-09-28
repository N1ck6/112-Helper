"""Методические материалы: загрузка файлов и передача в базу знаний ML (п.3.3)."""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import PageDep, SessionDep, require
from app.core.config import settings
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.pagination import Page, build_page
from app.core.permissions import Perm
from app.models.enums import MaterialKind
from app.schemas.common import MessageResponse
from app.schemas.scenario import MaterialRead
from app.services.scenarios import MaterialService

router = APIRouter(prefix="/materials", tags=["Методические материалы"])

ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".xlsx", ".json", ".xml", ".mp3", ".wav"}
CHUNK_SIZE = 1024 * 1024
BULK_MAX_FILES = 200
BULK_EXPANSION_FACTOR = 4


@router.get("", response_model=Page[MaterialRead], summary="Список материалов")
async def list_materials(
    session: SessionDep,
    page: PageDep,
    kind: MaterialKind | None = Query(None),
    _=Depends(require(Perm.MATERIALS_READ)),
) -> Page[MaterialRead]:
    items, total = await MaterialService(session).list_materials(page, kind=kind)
    return build_page([MaterialRead.model_validate(item) for item in items], total, page)


@router.post(
    "",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить материал",
    description=(
        "Принимает файл (памятка АРМ-112, классификатор, билеты, аудиозаписи). "
        "Файл сохраняется в локальном хранилище, запись — в БД."
    ),
)
async def upload_material(
    session: SessionDep,
    request: Request,
    file: UploadFile = File(..., description="Файл материала"),
    title: str = Form(...),
    kind: MaterialKind = Form(MaterialKind.DOC),
    category_id: uuid.UUID | None = Form(None),
    description: str | None = Form(None),
    actor=Depends(require(Perm.MATERIALS_WRITE)),
) -> MaterialRead:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise BusinessRuleError(
            f"Недопустимый тип файла «{suffix}». Разрешены: {', '.join(sorted(ALLOWED_SUFFIXES))}"
        )

    settings.ensure_storage()
    target = settings.uploads_path / f"{uuid.uuid4().hex}{suffix}"
    digest = hashlib.sha256()
    size = 0
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024

    with target.open("wb") as stream:
        while chunk := await file.read(CHUNK_SIZE):
            size += len(chunk)
            if size > limit:
                stream.close()
                target.unlink(missing_ok=True)
                raise BusinessRuleError(f"Файл превышает лимит {settings.MAX_UPLOAD_MB} МБ")
            digest.update(chunk)
            stream.write(chunk)

    material = await MaterialService(session).register(
        title=title,
        kind=kind,
        file_path=str(target),
        mime_type=file.content_type,
        size_bytes=size,
        checksum=digest.hexdigest(),
        category_id=category_id,
        description=description,
        actor=actor,
        request=request,
    )
    return MaterialRead.model_validate(material)


@router.post(
    "/bulk",
    response_model=list[MaterialRead],
    status_code=status.HTTP_201_CREATED,
    summary="Пакетный импорт материалов (ZIP)",
    description=(
        "Загружает архив с методическими материалами: памятками, классификаторами, "
        "билетами (п.2.9 ТЗ, пакетный импорт обновлений). Каждый файл внутри архива "
        "регистрируется отдельным материалом; недопустимые типы пропускаются."
    ),
)
async def bulk_upload(
    session: SessionDep,
    request: Request,
    file: UploadFile = File(..., description="Архив .zip с файлами материалов"),
    kind: MaterialKind = Form(MaterialKind.DOC),
    category_id: uuid.UUID | None = Form(None),
    actor=Depends(require(Perm.MATERIALS_WRITE)),
) -> list[MaterialRead]:
    if not (file.filename or "").lower().endswith(".zip"):
        raise BusinessRuleError("Ожидается ZIP-архив с материалами")

    settings.ensure_storage()
    payload = await file.read()
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(payload) > limit:
        raise BusinessRuleError(f"Архив превышает лимит {settings.MAX_UPLOAD_MB} МБ")

    service = MaterialService(session)
    created: list[MaterialRead] = []
    extracted = 0
    total_limit = limit * BULK_EXPANSION_FACTOR
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for entry in archive.infolist()[:BULK_MAX_FILES]:
                #: Пути внутри архива игнорируются: защита от «zip slip».
                name = Path(entry.filename).name
                if entry.is_dir() or not name or name.startswith("."):
                    continue
                suffix = Path(name).suffix.lower()
                if suffix not in ALLOWED_SUFFIXES or entry.file_size > limit:
                    continue

                content = archive.read(entry)
                extracted += len(content)
                if extracted > total_limit:
                    raise BusinessRuleError(
                        f"Содержимое архива превышает {total_limit // (1024 * 1024)} МБ "
                        "в распакованном виде"
                    )
                target = settings.uploads_path / f"{uuid.uuid4().hex}{suffix}"
                target.write_bytes(content)
                material = await service.register(
                    title=Path(name).stem,
                    kind=kind,
                    file_path=str(target),
                    mime_type=None,
                    size_bytes=len(content),
                    checksum=hashlib.sha256(content).hexdigest(),
                    category_id=category_id,
                    description=f"Импортировано из архива {file.filename}",
                    actor=actor,
                    request=request,
                )
                created.append(MaterialRead.model_validate(material))
    except zipfile.BadZipFile as exc:
        raise BusinessRuleError("Файл не является корректным ZIP-архивом") from exc

    if not created:
        raise BusinessRuleError(
            f"В архиве нет подходящих файлов. Разрешены: {', '.join(sorted(ALLOWED_SUFFIXES))}"
        )
    return created


@router.post(
    "/{material_id}/index",
    summary="Передать материал в базу знаний ML",
)
async def index_material(
    material_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.MATERIALS_WRITE))
) -> dict[str, Any]:
    return await MaterialService(session).send_to_knowledge_base(material_id)


@router.get("/{material_id}/download", summary="Скачать материал")
async def download_material(
    material_id: uuid.UUID, session: SessionDep, _=Depends(require(Perm.MATERIALS_READ))
) -> FileResponse:
    material = await MaterialService(session).materials.get_or_fail(material_id, "Материал не найден")
    if not material.file_path or not Path(material.file_path).exists():
        raise NotFoundError("Файл материала не найден в хранилище")
    return FileResponse(
        material.file_path,
        media_type=material.mime_type or "application/octet-stream",
        filename=f"{material.title}{Path(material.file_path).suffix}",
    )


@router.delete("/{material_id}", response_model=MessageResponse, summary="Удалить материал")
async def delete_material(
    material_id: uuid.UUID,
    session: SessionDep,
    request: Request,
    actor=Depends(require(Perm.MATERIALS_WRITE)),
) -> MessageResponse:
    await MaterialService(session).delete(material_id, actor, request)
    return MessageResponse(detail="Материал удалён из активных")
