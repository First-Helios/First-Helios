"""Venue identity models -- the `canonical` layer's answer to "which restaurant is this?".

Five tables plus a join table, per RFC-0001 D2:

- `brand`          -- chain identity, so chain-wide facts fan out to locations
- `venue`          -- a canonical physical location
- `venue_alias`    -- alternate names/spellings feeding the fingerprint matcher
- `venue_source`   -- where we know this venue from; the dedup/merge audit trail
- `site_identity`  -- a canonicalized website URL
- `venue_site`     -- venue <-> site, many-to-many

**No food-specific columns live here.** RFC-0001 D1.4 keeps venue identity
vertical-agnostic so a future non-food price index reuses it untouched. The
food-specific menu graph is a separate module.

**Enums are Postgres CHECK constraints, not native ENUM types.** Adding a
value to a native enum needs `ALTER TYPE`, which does not roll back inside a
transaction on older Postgres; a CHECK is edited by a plain migration. The
allowed values are module-level tuples so application code and the database
agree on one list.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.helios_core.db.base import SCHEMA_CANONICAL, Base, TimestampMixin

VENUE_STATUSES = ("open", "closed", "unknown")
"""Operating status. `unknown` is the honest default: discovery tells us a
venue exists, not that it is still trading."""

VENUE_SOURCE_KINDS = ("overture", "osm", "manual")
"""Where a venue record came from. Extended only alongside a real ingest path."""

SITE_RESOLUTION_METHODS = ("overture_website", "osm_tag", "manual")
"""How a venue got linked to a site (RFC-0001 D3.2)."""

SITE_LIVENESS_STATUSES = ("unknown", "live", "dead", "redirected")
"""Result of the last liveness check. `unknown` until one has run."""


def _in_check(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    """Build a `column IN (...)` CHECK with an explicit, stable name.

    Constraint names are given explicitly rather than via a MetaData naming
    convention: this schema is hand-reviewed, and a name that reads the same
    in the model, the migration, and a failing test is worth the verbosity.
    """
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class Brand(TimestampMixin, Base):
    """A chain identity. Independent venues simply have no brand."""

    __tablename__ = "brand"
    __table_args__: Any = (
        UniqueConstraint("name_fingerprint", name="uq_brand_name_fingerprint"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_brand_name_not_blank"),
        CheckConstraint(
            "length(btrim(name_fingerprint)) > 0", name="ck_brand_fingerprint_not_blank"
        ),
        {"schema": SCHEMA_CANONICAL},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Normalized grouping key ("H-E-B #765" and "HEB GROCERY #404" collapse
    # together). Populated by the identity module in RFC-0001 PR 5; unique so
    # two spellings cannot create two brands.
    name_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(Text)

    venues: Mapped[list[Venue]] = relationship(back_populates="brand")

    def __repr__(self) -> str:
        return f"Brand(id={self.id!r}, name={self.name!r})"


class Venue(TimestampMixin, Base):
    """A canonical physical location.

    Address is kept both as captured (`address_raw`) and as normalized parts.
    The raw form is provenance -- it is what the source actually said, and
    re-normalizing later must not require re-fetching.
    """

    __tablename__ = "venue"
    __table_args__: Any = (
        _in_check("status", VENUE_STATUSES, "ck_venue_status"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_venue_name_not_blank"),
        CheckConstraint("lat IS NULL OR (lat BETWEEN -90 AND 90)", name="ck_venue_lat_range"),
        CheckConstraint("lng IS NULL OR (lng BETWEEN -180 AND 180)", name="ck_venue_lng_range"),
        # A half-geocoded venue is a bug, not a state worth representing.
        CheckConstraint(
            "(lat IS NULL) = (lng IS NULL)",
            name="ck_venue_coords_both_or_neither",
        ),
        Index("ix_venue_name_fingerprint", "name_fingerprint"),
        Index("ix_venue_h3_r8", "h3_r8"),
        # Covers both the chain fan-out query (`WHERE brand_id = ?`, the
        # reason `brand` exists) and the ON DELETE SET NULL scan.
        Index("ix_venue_brand_id", "brand_id"),
        {"schema": SCHEMA_CANONICAL},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_fingerprint: Mapped[str | None] = mapped_column(String(255))

    # SET NULL, not CASCADE: de-listing a chain must not delete the physical
    # restaurants, which keep existing regardless of what we know about the brand.
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA_CANONICAL}.brand.id", ondelete="SET NULL", name="fk_venue_brand_id")
    )

    address_raw: Mapped[str | None] = mapped_column(Text)
    street: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    region: Mapped[str | None] = mapped_column(String(64))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(2))

    lat: Mapped[float | None] = mapped_column(Double)
    lng: Mapped[float | None] = mapped_column(Double)
    # H3 cell ids as 15-char hex. Populated on insert from lat/lng in
    # RFC-0001 PR 5; r8 is indexed because it is the metro-scale query unit.
    h3_r6: Mapped[str | None] = mapped_column(String(16))
    h3_r8: Mapped[str | None] = mapped_column(String(16))
    h3_r9: Mapped[str | None] = mapped_column(String(16))

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")

    # Discovery provenance: when this venue first appeared in a source, and
    # when a source last confirmed it. Disappearance is information, so rows
    # are never deleted -- `last_seen_at` simply stops advancing.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    brand: Mapped[Brand | None] = relationship(back_populates="venues")
    aliases: Mapped[list[VenueAlias]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )
    sources: Mapped[list[VenueSource]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )
    site_links: Mapped[list[VenueSite]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Venue(id={self.id!r}, name={self.name!r})"


class VenueAlias(TimestampMixin, Base):
    """An alternate name for a venue, feeding the fingerprint matcher."""

    __tablename__ = "venue_alias"
    __table_args__: Any = (
        # One alias per venue per normalized form. Re-running discovery
        # re-proposes the same aliases; this is what makes that a no-op.
        UniqueConstraint("venue_id", "alias_fingerprint", name="uq_venue_alias_venue_fingerprint"),
        CheckConstraint("length(btrim(alias)) > 0", name="ck_venue_alias_not_blank"),
        # Same provenance vocabulary as `venue_source.source`, and pinned for
        # the same reason: an unconstrained column whose purpose is grouping
        # will accumulate "overture", "Overture" and "overture_maps".
        _in_check("source", VENUE_SOURCE_KINDS, "ck_venue_alias_source_kind"),
        {"schema": SCHEMA_CANONICAL},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # CASCADE: an alias has no meaning without the venue it names.
    venue_id: Mapped[int] = mapped_column(
        ForeignKey(
            f"{SCHEMA_CANONICAL}.venue.id", ondelete="CASCADE", name="fk_venue_alias_venue_id"
        ),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable: an alias may predate knowing where it came from. A NULL passes
    # the CHECK, which is the intended "not recorded" case.
    source: Mapped[str | None] = mapped_column(String(16))

    venue: Mapped[Venue] = relationship(back_populates="aliases")

    def __repr__(self) -> str:
        return f"VenueAlias(id={self.id!r}, alias={self.alias!r})"


class VenueSource(TimestampMixin, Base):
    """Where we know a venue from -- one row per (external source, external id).

    This is the dedup/merge audit trail: when two external records resolve to
    one venue, both rows survive pointing at the same `venue_id`, so the merge
    is inspectable rather than lossy.
    """

    __tablename__ = "venue_source"
    __table_args__: Any = (
        # An external record describes exactly one venue. This is the
        # constraint that makes re-ingesting an Overture snapshot idempotent.
        UniqueConstraint("source", "external_id", name="uq_venue_source_source_external_id"),
        _in_check("source", VENUE_SOURCE_KINDS, "ck_venue_source_kind"),
        CheckConstraint("length(btrim(external_id)) > 0", name="ck_venue_source_external_id"),
        Index("ix_venue_source_venue_id", "venue_id"),
        {"schema": SCHEMA_CANONICAL},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(
        ForeignKey(
            f"{SCHEMA_CANONICAL}.venue.id", ondelete="CASCADE", name="fk_venue_source_venue_id"
        ),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # The external record as received. Kept so a re-match can be re-run from
    # the database without re-querying Overture or Overpass.
    raw_identity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    venue: Mapped[Venue] = relationship(back_populates="sources")

    def __repr__(self) -> str:
        return (
            f"VenueSource(id={self.id!r}, source={self.source!r}, external_id={self.external_id!r})"
        )


class SiteIdentity(TimestampMixin, Base):
    """A canonicalized website URL.

    Deliberately *not* owned by a venue: chain sites serve many locations, so
    the venue link lives in `venue_site`. `url_canonical` is unique, which is
    what lets one site be shared rather than duplicated per location.
    """

    __tablename__ = "site_identity"
    __table_args__: Any = (
        UniqueConstraint("url_canonical", name="uq_site_identity_url_canonical"),
        _in_check("liveness_status", SITE_LIVENESS_STATUSES, "ck_site_identity_liveness_status"),
        CheckConstraint("length(btrim(url_canonical)) > 0", name="ck_site_identity_url_not_blank"),
        {"schema": SCHEMA_CANONICAL},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    url_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    # As found, before canonicalization -- provenance for debugging a bad
    # canonicalization without re-fetching the source.
    url_original: Mapped[str | None] = mapped_column(Text)
    liveness_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="unknown"
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    venue_links: Mapped[list[VenueSite]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"SiteIdentity(id={self.id!r}, url_canonical={self.url_canonical!r})"


class VenueSite(TimestampMixin, Base):
    """Venue <-> site, many-to-many, carrying how the link was resolved.

    RFC-0001 D2 lists five identity tables and then specifies a relationship
    they cannot express: "a venue may have 0..n sites; a site may serve many
    venues (chain sites)". This join table is that relationship.
    """

    __tablename__ = "venue_site"
    __table_args__: Any = (
        _in_check("resolution_method", SITE_RESOLUTION_METHODS, "ck_venue_site_resolution_method"),
        Index("ix_venue_site_site_identity_id", "site_identity_id"),
        {"schema": SCHEMA_CANONICAL},
    )

    # Composite PK: the pair is the identity, and it makes re-resolving a
    # website a no-op rather than a duplicate row.
    venue_id: Mapped[int] = mapped_column(
        ForeignKey(
            f"{SCHEMA_CANONICAL}.venue.id", ondelete="CASCADE", name="fk_venue_site_venue_id"
        ),
        primary_key=True,
    )
    site_identity_id: Mapped[int] = mapped_column(
        ForeignKey(
            f"{SCHEMA_CANONICAL}.site_identity.id",
            ondelete="CASCADE",
            name="fk_venue_site_site_identity_id",
        ),
        primary_key=True,
    )
    resolution_method: Mapped[str] = mapped_column(String(32), nullable=False)

    venue: Mapped[Venue] = relationship(back_populates="site_links")
    site: Mapped[SiteIdentity] = relationship(back_populates="venue_links")

    def __repr__(self) -> str:
        return f"VenueSite(venue_id={self.venue_id!r}, site_identity_id={self.site_identity_id!r})"
