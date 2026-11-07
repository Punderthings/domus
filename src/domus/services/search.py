"""Full-text search over devices and areas (data-storage-backup.md 2.5).

One ``SearchIndex`` interface with two engines behind it:

- SQLite: an FTS5 virtual table, ``search_fts``.
- PostgreSQL: a ``search_doc`` table with generated ``tsvector`` columns and a
  ``pg_trgm`` index on the title, so near misses ("thermostst") still match.

Each indexed record becomes one document with three text fields:

- ``title``: the record's name.
- ``public_text``: what a guest may see too (notes, product, tags, area, location).
- ``private_text``: what guests never see (serials, MAC and other identifiers,
  vendor). Guest searches never match it, so a search cannot reveal a serial
  number that the guest response schemas leave out.

The index is kept in sync from the application, not by database triggers, so
both engines behave the same: a session listener (``install``) refreshes the
documents touched by each commit, and bulk writes such as a backup import call
``rebuild``. Access rules are applied to the results by the caller, the same
way list endpoints apply them.

These tables are derived data. They are not on ``Base.metadata``, so backups
and the JSONL export never carry them, and a restore rebuilds them.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    Float,
    MetaData,
    String,
    Table,
    Text,
    delete,
    event,
    func,
    insert,
    literal_column,
    select,
    text,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from domus.models import (
    Area,
    Asset,
    AssetIdentifier,
    AssetTag,
    Building,
    Floor,
    Location,
    Product,
    Tag,
)

# Tables whose names start with this belong to the search index. Migrations
# and the schema comparison skip them (FTS5 also creates shadow tables).
TABLE_PREFIX = "search_"

ASSET = "asset"
AREA = "area"

MAX_TERMS = 8
# Letters and digits only. Splitting on everything else (including "_") gives
# the same terms on both engines and leaves no query syntax to inject.
_TERM = re.compile(r"[^\W_]+")


def query_terms(raw: str) -> list[str]:
    """Split user input into lowercase search terms, at most ``MAX_TERMS`` of them."""
    return [t.lower() for t in _TERM.findall(raw)][:MAX_TERMS]


def is_search_table(name: str | None) -> bool:
    return name is not None and name.startswith(TABLE_PREFIX)


def include_in_migrations(name: str | None, type_: str, _parent_names: object) -> bool:
    """Alembic ``include_name`` hook: the search tables are managed by hand-written SQL."""
    return type_ != "table" or not is_search_table(name)


@dataclass(frozen=True)
class SearchDoc:
    kind: str
    ref_id: str
    property_id: str
    title: str
    public_text: str
    private_text: str


@dataclass(frozen=True)
class Hit:
    kind: str
    ref_id: str


def _join(parts: Iterable[str | None]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


# --- Building documents from the data -----------------------------------------


def _asset_docs(conn: Connection, asset_ids: Sequence[str] | None) -> list[SearchDoc]:
    """Documents for the given assets (all assets when ``asset_ids`` is None).

    Deleted assets, and ids that no longer exist, produce no document.
    """
    a = Asset.__table__
    stmt = select(
        a.c.id,
        a.c.property_id,
        a.c.name,
        a.c.category,
        a.c.notes,
        a.c.vendor,
        a.c.product_id,
        a.c.location_id,
    ).where(a.c.deleted_at.is_(None))
    if asset_ids is not None:
        if not asset_ids:
            return []
        stmt = stmt.where(a.c.id.in_(asset_ids))
    assets = list(conn.execute(stmt))
    if not assets:
        return []
    ids = [r.id for r in assets]

    p = Product.__table__
    product_ids = {r.product_id for r in assets if r.product_id}
    products: dict[str, str] = {}
    if product_ids:
        for r in conn.execute(
            select(p.c.id, p.c.manufacturer, p.c.model, p.c.model_id).where(
                p.c.id.in_(product_ids), p.c.deleted_at.is_(None)
            )
        ):
            products[r.id] = _join([r.manufacturer, r.model, r.model_id])

    loc, ar = Location.__table__, Area.__table__
    location_ids = {r.location_id for r in assets if r.location_id}
    places: dict[str, str] = {}
    if location_ids:
        for r in conn.execute(
            select(loc.c.id, loc.c.name, ar.c.name.label("area_name"))
            .join(ar, ar.c.id == loc.c.area_id)
            .where(loc.c.id.in_(location_ids), loc.c.deleted_at.is_(None))
        ):
            places[r.id] = _join([r.name, r.area_name])

    tg, at = Tag.__table__, AssetTag.__table__
    tags: dict[str, list[str]] = defaultdict(list)
    for r in conn.execute(
        select(at.c.asset_id, tg.c.name)
        .join(tg, tg.c.id == at.c.tag_id)
        .where(at.c.asset_id.in_(ids), tg.c.deleted_at.is_(None))
    ):
        tags[r.asset_id].append(r.name)

    ai = AssetIdentifier.__table__
    idents: dict[str, list[str]] = defaultdict(list)
    for r in conn.execute(
        select(ai.c.asset_id, ai.c.value).where(ai.c.asset_id.in_(ids), ai.c.deleted_at.is_(None))
    ):
        idents[r.asset_id].append(r.value)

    return [
        SearchDoc(
            kind=ASSET,
            ref_id=r.id,
            property_id=r.property_id,
            title=r.name,
            public_text=_join(
                [
                    r.category.replace("_", " "),
                    r.notes,
                    products.get(r.product_id or ""),
                    places.get(r.location_id or ""),
                    *sorted(tags[r.id]),
                ]
            ),
            private_text=_join([r.vendor, *idents[r.id]]),
        )
        for r in assets
    ]


def _area_docs(conn: Connection, area_ids: Sequence[str] | None) -> list[SearchDoc]:
    ar, b, f = Area.__table__, Building.__table__, Floor.__table__
    stmt = (
        select(
            ar.c.id,
            ar.c.property_id,
            ar.c.name,
            ar.c.kind,
            b.c.name.label("building_name"),
            f.c.name.label("floor_name"),
        )
        .outerjoin(b, b.c.id == ar.c.building_id)
        .outerjoin(f, f.c.id == ar.c.floor_id)
        .where(ar.c.deleted_at.is_(None))
    )
    if area_ids is not None:
        if not area_ids:
            return []
        stmt = stmt.where(ar.c.id.in_(area_ids))
    return [
        SearchDoc(
            kind=AREA,
            ref_id=r.id,
            property_id=r.property_id,
            title=r.name,
            public_text=_join([r.kind.replace("_", " "), r.floor_name, r.building_name]),
            private_text="",
        )
        for r in conn.execute(stmt)
    ]


# --- Engines -------------------------------------------------------------------


class SearchIndex(Protocol):
    def replace(self, conn: Connection, kind: str, ids: Sequence[str] | None) -> None:
        """Re-index ``ids`` of ``kind`` (every record of that kind when ``ids`` is None)."""
        ...

    def search(
        self,
        conn: Connection,
        property_id: str,
        terms: Sequence[str],
        *,
        include_private: bool,
        limit: int,
        offset: int = 0,
    ) -> list[Hit]:
        """Best matches first. ``terms`` come from :func:`query_terms`."""
        ...


def _docs(conn: Connection, kind: str, ids: Sequence[str] | None) -> list[SearchDoc]:
    return _asset_docs(conn, ids) if kind == ASSET else _area_docs(conn, ids)


def _rows(docs: Iterable[SearchDoc]) -> list[dict[str, str]]:
    return [
        {
            "kind": d.kind,
            "ref_id": d.ref_id,
            "property_id": d.property_id,
            "title": d.title,
            "public_text": d.public_text,
            "private_text": d.private_text,
        }
        for d in docs
    ]


# SQLite: FTS5 ------------------------------------------------------------------

SQLITE_TABLE = "search_fts"  # created by migration 0003
_fts_meta = MetaData()
_fts = Table(
    SQLITE_TABLE,
    _fts_meta,
    Column("kind", Text),
    Column("ref_id", Text),
    Column("property_id", Text),
    Column("title", Text),
    Column("public_text", Text),
    Column("private_text", Text),
)


def fts5_match(terms: Sequence[str], *, include_private: bool) -> str:
    """An FTS5 MATCH expression: every term must match as a prefix.

    Terms are letters and digits only, and each is quoted, so FTS5 keywords
    such as NOT or NEAR are matched as words.
    """
    expr = " ".join(f'"{t}"*' for t in terms)
    if include_private:
        return expr
    return "{title public_text} : (" + expr + ")"


class SqliteSearchIndex:
    def replace(self, conn: Connection, kind: str, ids: Sequence[str] | None) -> None:
        stmt = delete(_fts).where(_fts.c.kind == kind)
        if ids is not None:
            if not ids:
                return
            stmt = stmt.where(_fts.c.ref_id.in_(ids))
        conn.execute(stmt)
        rows = _rows(_docs(conn, kind, ids))
        if rows:
            conn.execute(insert(_fts), rows)

    def search(
        self,
        conn: Connection,
        property_id: str,
        terms: Sequence[str],
        *,
        include_private: bool,
        limit: int,
        offset: int = 0,
    ) -> list[Hit]:
        if not terms:
            return []
        # bm25 weights per column, in table order: a title match counts most.
        rank = literal_column(f"bm25({SQLITE_TABLE}, 0, 0, 0, 10.0, 3.0, 2.0)", Float())
        stmt = (
            select(_fts.c.kind, _fts.c.ref_id)
            .where(
                literal_column(SQLITE_TABLE).op("MATCH")(
                    fts5_match(terms, include_private=include_private)
                ),
                _fts.c.property_id == property_id,
            )
            .order_by(rank, _fts.c.ref_id)
            .limit(limit)
            .offset(offset)
        )
        return [Hit(r.kind, r.ref_id) for r in conn.execute(stmt)]


# PostgreSQL: tsvector + pg_trgm -----------------------------------------------

PG_TABLE = "search_doc"
# The tables are created by migration 0003. 'simple' does no stemming, which
# suits model numbers, serials, and names in any language.
_pg_meta = MetaData()
_doc = Table(
    PG_TABLE,
    _pg_meta,
    Column("kind", String(16), primary_key=True),
    Column("ref_id", String(36), primary_key=True),
    Column("property_id", String(36)),
    Column("title", Text),
    Column("public_text", Text),
    Column("private_text", Text),
    Column("public_tsv", Text),  # tsvector; only used in expressions here
    Column("all_tsv", Text),
)


def tsquery_text(terms: Sequence[str]) -> str:
    """A ``to_tsquery`` string: every term as a prefix, all required."""
    return " & ".join(f"{t}:*" for t in terms)


# pg_trgm's own default for word similarity (pg_trgm.word_similarity_threshold).
WORD_SIMILARITY_THRESHOLD = 0.6


def normalize_for_postgres(value: str) -> str:
    """Letters and digits only, split the way :func:`query_terms` splits queries.

    The Postgres text parser reads "SN-77441" as the word "sn" and the
    number "-77441", so a search for "77441" would miss it. Indexing the same
    terms a query produces keeps both engines in step.
    """
    return " ".join(t.lower() for t in _TERM.findall(value))


class PostgresSearchIndex:
    def replace(self, conn: Connection, kind: str, ids: Sequence[str] | None) -> None:
        stmt = delete(_doc).where(_doc.c.kind == kind)
        if ids is not None:
            if not ids:
                return
            stmt = stmt.where(_doc.c.ref_id.in_(ids))
        conn.execute(stmt)
        rows = _rows(_docs(conn, kind, ids))
        for row in rows:
            for key in ("title", "public_text", "private_text"):
                row[key] = normalize_for_postgres(row[key])
        if rows:
            conn.execute(insert(_doc), rows)

    def search(
        self,
        conn: Connection,
        property_id: str,
        terms: Sequence[str],
        *,
        include_private: bool,
        limit: int,
        offset: int = 0,
    ) -> list[Hit]:
        if not terms:
            return []
        tsv = _doc.c.all_tsv if include_private else _doc.c.public_tsv
        query = func.to_tsquery(text("'simple'"), tsquery_text(terms))
        phrase = " ".join(terms)
        # Near misses ("hallwya") match on the title through pg_trgm's word
        # similarity. The function form is used rather than the ``<%``
        # operator, whose "%" the driver would read as a parameter marker.
        similarity: ColumnElement[Any] = func.word_similarity(phrase, _doc.c.title)
        near_miss = similarity >= WORD_SIMILARITY_THRESHOLD
        matched = tsv.op("@@", return_type=Boolean)(query)
        rank = func.ts_rank(tsv, query) + similarity
        stmt = (
            select(_doc.c.kind, _doc.c.ref_id)
            .where(
                _doc.c.property_id == property_id,
                matched | near_miss,
            )
            .order_by(rank.desc(), _doc.c.ref_id)
            .limit(limit)
            .offset(offset)
        )
        return [Hit(r.kind, r.ref_id) for r in conn.execute(stmt)]


def index_for(conn: Connection) -> SearchIndex:
    if conn.dialect.name == "postgresql":
        return PostgresSearchIndex()
    if conn.dialect.name == "sqlite":
        return SqliteSearchIndex()
    raise RuntimeError(f"search is not implemented for {conn.dialect.name}")


def rebuild(conn: Connection) -> None:
    """Re-index everything. Used after bulk writes such as a backup import."""
    index = index_for(conn)
    index.replace(conn, ASSET, None)
    index.replace(conn, AREA, None)


def is_empty(conn: Connection) -> bool:
    table = _doc if conn.dialect.name == "postgresql" else _fts
    return conn.execute(select(func.count()).select_from(table)).scalar_one() == 0


def ensure_built(conn: Connection) -> None:
    """Fill an empty index when there is data, such as right after the migration."""
    if not is_empty(conn):
        return
    a, ar = Asset.__table__, Area.__table__
    has_data = (
        conn.execute(
            select(func.count()).select_from(a).where(a.c.deleted_at.is_(None))
        ).scalar_one()
        or conn.execute(
            select(func.count()).select_from(ar).where(ar.c.deleted_at.is_(None))
        ).scalar_one()
    )
    if has_data:
        rebuild(conn)


# --- Keeping the index in sync with the ORM -------------------------------------

_PENDING = "domus.search.pending"


def _pending(session: Session) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = session.info.setdefault(_PENDING, set())
    return found


def mark_dirty(session: Session, kind: str, ref_id: str) -> None:
    """Re-index a record at commit. Needed only after Core statements that
    bypass the ORM, such as a bulk ``delete()``; ORM changes are seen anyway.
    """
    _pending(session).add((kind, ref_id))


def _marks_for(obj: object) -> list[tuple[str, str]]:
    match obj:
        case Asset():
            return [(ASSET, obj.id)]
        case AssetIdentifier() | AssetTag():
            return [(ASSET, obj.asset_id)]
        case Product():
            return [("product", obj.id)]
        case Tag():
            return [("tag", obj.id)]
        case Location():
            return [("location", obj.id)]
        case Area():
            return [(AREA, obj.id)]
        case Building():
            return [("building", obj.id)]
        case Floor():
            return [("floor", obj.id)]
        case _:
            return []


def _after_flush(session: Session, _ctx: object) -> None:
    pending = _pending(session)
    for obj in (*session.new, *session.dirty, *session.deleted):
        pending.update(_marks_for(obj))


def _resolve(conn: Connection, marks: set[tuple[str, str]]) -> tuple[set[str], set[str]]:
    """Turn marks on related records into the asset and area ids to re-index."""
    by_kind: dict[str, set[str]] = defaultdict(set)
    for kind, ref in marks:
        by_kind[kind].add(ref)
    assets = set(by_kind[ASSET])
    areas = set(by_kind[AREA])
    a, loc, at = Asset.__table__, Location.__table__, AssetTag.__table__
    ar = Area.__table__
    if by_kind["building"] or by_kind["floor"]:
        areas.update(
            conn.scalars(
                select(ar.c.id).where(
                    ar.c.building_id.in_(by_kind["building"]) | ar.c.floor_id.in_(by_kind["floor"])
                )
            )
        )
    if by_kind["product"]:
        assets.update(conn.scalars(select(a.c.id).where(a.c.product_id.in_(by_kind["product"]))))
    if by_kind["tag"]:
        assets.update(conn.scalars(select(at.c.asset_id).where(at.c.tag_id.in_(by_kind["tag"]))))
    location_ids = set(by_kind["location"])
    if by_kind[AREA]:
        location_ids.update(conn.scalars(select(loc.c.id).where(loc.c.area_id.in_(by_kind[AREA]))))
    if location_ids:
        assets.update(conn.scalars(select(a.c.id).where(a.c.location_id.in_(location_ids))))
    return assets, areas


def _before_commit(session: Session) -> None:
    session.flush()
    marks = session.info.pop(_PENDING, None)
    if not marks:
        return
    conn = session.connection()
    assets, areas = _resolve(conn, marks)
    index = index_for(conn)
    index.replace(conn, ASSET, sorted(assets))
    index.replace(conn, AREA, sorted(areas))


def _discard(session: Session, *_args: object) -> None:
    session.info.pop(_PENDING, None)


def install(factory: sessionmaker[Session]) -> None:
    """Keep the index in sync for every session ``factory`` makes.

    Call it once per factory (``make_session_factory`` does). There is no
    "already installed" check: SQLAlchemy's event registry is keyed by object
    id, so after garbage collection a new factory can look like an old one.
    """
    event.listen(factory, "after_flush", _after_flush)
    event.listen(factory, "before_commit", _before_commit)
    event.listen(factory, "after_rollback", _discard)


def search(
    conn: Connection,
    property_id: str,
    raw: str,
    *,
    include_private: bool,
    limit: int,
    offset: int = 0,
) -> list[Hit]:
    """Search one property. Returns hits only; callers apply access rules."""
    return index_for(conn).search(
        conn,
        property_id,
        query_terms(raw),
        include_private=include_private,
        limit=limit,
        offset=offset,
    )


__all__ = [
    "AREA",
    "ASSET",
    "Hit",
    "SearchIndex",
    "ensure_built",
    "include_in_migrations",
    "install",
    "is_search_table",
    "mark_dirty",
    "query_terms",
    "rebuild",
    "search",
]
