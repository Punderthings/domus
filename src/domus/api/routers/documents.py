"""File uploads and downloads: photos, floor plans, and manuals.

Uploads are sent as the raw request body (no multipart form), with the file
name and kind in the query string. The stored type comes from the file's
first bytes, and responses carry ``nosniff`` and a locked-down CSP so an
uploaded file can never run as a page.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from domus.api.common import audit, to_out
from domus.api.deps import (
    CurrentPrincipal,
    DbSession,
    PropertyContext,
    SettingsDep,
    not_found,
    property_context,
)
from domus.api.schemas import DocumentKind, DocumentOut, Sensitivity
from domus.models import Blob, Document
from domus.models.enums import IMAGE_MIME_TYPES, UPLOAD_MIME_TYPES, AccessLevel, Role
from domus.services import images
from domus.services.blobstore import LocalFsBlobStore, TooLarge
from domus.services.uploads import safe_filename, sniff_file

router = APIRouter(tags=["documents"])

# Who may read a document of each sensitivity.
SENSITIVITY_ROLE: dict[str, Role] = {
    "guest": Role.GUEST,
    "resident": Role.RESIDENT,
    "admin": Role.ADMIN,
}

UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "The file itself as the raw request body.",
        "content": {
            mime: {"schema": {"type": "string", "format": "binary"}} for mime in UPLOAD_MIME_TYPES
        },
    }
}


def blob_store(settings: SettingsDep) -> LocalFsBlobStore:
    return LocalFsBlobStore(settings.blobs_dir)


def content_url(doc: Document) -> str | None:
    return f"/api/v1/documents/{doc.id}/content" if doc.blob_sha256 else None


def document_out(ctx: PropertyContext, doc: Document) -> DocumentOut:
    blob = ctx.db.get(Blob, doc.blob_sha256) if doc.blob_sha256 else None
    level = AccessLevel.MANAGE if ctx.has_role(Role.MAINTAINER) else AccessLevel.VIEW
    return to_out(
        DocumentOut,
        doc,
        mime_type=blob.mime_type if blob else None,
        size=blob.size if blob else None,
        content_url=content_url(doc),
        access=level.value,
    )


def get_document(db: DbSession, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise not_found()
    return doc


def require_readable(ctx: PropertyContext, doc: Document) -> None:
    """Hide documents above the caller's role, such as receipts from guests."""
    if not ctx.has_role(SENSITIVITY_ROLE.get(doc.sensitivity, Role.ADMIN)):
        raise not_found()


def file_response(store: LocalFsBlobStore, blob: Blob, filename: str | None) -> FileResponse:
    path = store.path(blob.sha256)
    if not path.is_file():
        raise not_found()
    disposition = "inline" if blob.mime_type in IMAGE_MIME_TYPES else "attachment"
    if filename:
        disposition += f"; filename*=UTF-8''{quote(filename)}"
    return FileResponse(
        path,
        media_type=blob.mime_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.post("/documents", status_code=status.HTTP_201_CREATED, openapi_extra=UPLOAD_BODY)
async def upload_document(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    settings: SettingsDep,
    kind: DocumentKind = "photo",
    property_id: str | None = None,
    title: Annotated[str | None, Query(max_length=300)] = None,
    filename: Annotated[str | None, Query(max_length=300)] = None,
    sensitivity: Sensitivity = "resident",
) -> DocumentOut:
    """Upload one file. JPEG, PNG, WebP, GIF, and PDF are accepted."""
    ctx = property_context(db, principal, property_id)
    ctx.require_role(Role.RESIDENT)
    if not ctx.has_role(SENSITIVITY_ROLE[sensitivity]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot upload above your own role")
    store = blob_store(settings)
    try:
        staged = await store.stage_stream(request.stream(), max_bytes=settings.upload_max_bytes)
    except TooLarge:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File is larger than {settings.upload_max_bytes} bytes",
        ) from None
    try:
        mime = sniff_file(staged)
        if mime is None:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "Unsupported file type; upload JPEG, PNG, WebP, GIF, or PDF",
            )
        if mime in IMAGE_MIME_TYPES:
            try:
                staged, mime = await run_in_threadpool(images.sanitize, staged, store, mime)
            except images.BadImage as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        stored = await run_in_threadpool(store.commit, staged)
    finally:
        staged.unlink(missing_ok=True)

    if db.get(Blob, stored.sha256) is None:
        db.add(Blob(sha256=stored.sha256, size=stored.size, mime_type=mime))
    doc = Document(
        property_id=ctx.property_id,
        blob_sha256=stored.sha256,
        kind=kind,
        title=title,
        original_filename=safe_filename(filename),
        sensitivity=sensitivity,
        captured_at=None,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
    )
    db.add(doc)
    db.flush()
    audit(ctx, "create", "document", doc.id, {"kind": kind, "sha256": stored.sha256})
    return document_out(ctx, doc)


@router.get("/documents/{document_id}")
def get_document_meta(document_id: str, db: DbSession, principal: CurrentPrincipal) -> DocumentOut:
    doc = get_document(db, document_id)
    ctx = property_context(db, principal, doc.property_id)
    require_readable(ctx, doc)
    return document_out(ctx, doc)


@router.get(
    "/documents/{document_id}/content",
    response_class=FileResponse,
    responses={200: {"content": {m: {} for m in UPLOAD_MIME_TYPES}}},
)
def get_document_content(
    document_id: str, db: DbSession, principal: CurrentPrincipal, settings: SettingsDep
) -> FileResponse:
    doc = get_document(db, document_id)
    ctx = property_context(db, principal, doc.property_id)
    require_readable(ctx, doc)
    blob = db.get(Blob, doc.blob_sha256) if doc.blob_sha256 else None
    if blob is None:
        raise not_found()
    return file_response(blob_store(settings), blob, doc.original_filename)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: DbSession, principal: CurrentPrincipal) -> None:
    """Soft-delete a document. The blob stays until a later cleanup job finds it unused."""
    doc = get_document(db, document_id)
    ctx = property_context(db, principal, doc.property_id)
    require_readable(ctx, doc)
    if doc.created_by != ctx.user_id:
        ctx.require_role(Role.MAINTAINER)
    doc.deleted_at = datetime.now(UTC)
    doc.updated_by = ctx.user_id
    audit(ctx, "delete", "document", doc.id)
