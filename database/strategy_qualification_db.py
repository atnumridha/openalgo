"""Durable prospective evidence with atomic reconciliation and release revisions."""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.orm import Session, declarative_base

from database.engine_factory import create_db_engine
from services.risk.qualification import POLICY, evaluate_trade, timestamp

Base = declarative_base()
MAX_CAMPAIGNS = 20
MAX_TRADES = 2000
MAX_AUDITS = 2000


def canonical(value):
    def convert(item):
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError("Unsupported evidence value")

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=convert, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def bounded(value):
    encoded = canonical(value)
    if len(encoded) > 131072:
        raise ValueError("Execution evidence exceeds the storage limit")
    return json.loads(encoded)


def iso(now):
    return now.astimezone(UTC).isoformat()


class QualificationCampaign(Base):
    __tablename__ = "sq_campaign"
    id = Column(Integer, primary_key=True)
    owner = Column(String(200), nullable=False, index=True)
    strategy_id = Column(Integer, nullable=False, index=True)
    final_run_id = Column(Integer, nullable=False)
    active_key = Column(String(64), unique=True)
    binding_hash = Column(String(64), nullable=False)
    binding = Column(JSON, nullable=False)
    final_run = Column(JSON, nullable=False)
    created_at = Column(String(40), nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    max_drawdown_pct = Column(Float, nullable=False, default=0)
    peak_equity = Column(Float, nullable=False, default=10000)
    risk_breach = Column(Boolean, nullable=False, default=False)
    reconciliation = Column(JSON)
    approval = Column(JSON)
    __table_args__ = (UniqueConstraint("owner", "strategy_id", "binding_hash"),)


class QualificationTrade(Base):
    __tablename__ = "sq_trade"
    owner = Column(String(200), primary_key=True)
    trade_ref = Column(String(64), primary_key=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    registered_at = Column(String(40), nullable=False)
    quotes = Column(JSON, nullable=False, default=dict)
    risk_row = Column(JSON)
    mark_gap = Column(Boolean, nullable=False, default=False)
    evidence_error = Column(String(300))
    marked_net = Column(Float, nullable=False, default=0)


class QualificationAudit(Base):
    __tablename__ = "sq_audit"
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    owner = Column(String(200), nullable=False)
    kind = Column(String(30), nullable=False)
    at = Column(String(40), nullable=False)
    details = Column(JSON, nullable=False)


class QualificationStore:
    def __init__(self, database_url=None, *, engine=None):
        self.engine = engine if engine is not None else create_db_engine(database_url)

    def init_db(self):
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        # SQLite's short write lock serializes competing registrations, evidence
        # revisions and approvals. No broker or context calls occur inside it.
        with Session(self.engine, expire_on_commit=False) as db:
            try:
                if self.engine.dialect.name == "sqlite":
                    db.execute(text("BEGIN IMMEDIATE"))
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _campaign(self, db, owner, campaign_id):
        return db.scalar(
            select(QualificationCampaign)
            .where(QualificationCampaign.owner == owner, QualificationCampaign.id == campaign_id)
            .with_for_update()
        )

    def _audit(self, db, campaign, kind, details, now):
        count = db.scalar(
            select(func.count())
            .select_from(QualificationAudit)
            .where(QualificationAudit.campaign_id == campaign.id)
        )
        # Keep one emergency revocation slot beyond the normal review budget.
        # Once used, every further approval is refused by the ordinary bound.
        if count >= MAX_AUDITS and not (kind == "revoked" and count == MAX_AUDITS):
            raise ValueError("Campaign review history limit reached; archive this deployment")
        db.add(
            QualificationAudit(
                campaign_id=campaign.id,
                owner=campaign.owner,
                kind=kind,
                at=iso(now),
                details=bounded(details),
            )
        )

    def _changed(self, campaign):
        campaign.revision += 1
        if campaign.reconciliation:
            campaign.reconciliation = campaign.reconciliation | {"status": "stale"}
        if campaign.approval and campaign.approval["status"] == "approved":
            campaign.approval = campaign.approval | {
                "status": "invalidated",
                "invalidation_reason": "Campaign evidence changed; reconcile and approve again.",
            }

    def _snapshot(self, db, campaign):
        if campaign is None:
            return None
        rows = db.scalars(
            select(QualificationTrade)
            .where(
                QualificationTrade.campaign_id == campaign.id,
                QualificationTrade.owner == campaign.owner,
            )
            .order_by(QualificationTrade.registered_at, QualificationTrade.trade_ref)
            .limit(MAX_TRADES + 1)
        ).all()
        if len(rows) > MAX_TRADES:
            raise ValueError("Campaign evidence storage limit exceeded")
        trades = []
        raw = []
        for row in rows:
            evidence = row.risk_row or {}
            value = evaluate_trade(evidence, row.quotes, campaign.binding, row.registered_at)
            if row.evidence_error:
                value["valid"] = False
                value["issues"].append(row.evidence_error)
            value.update(trade_ref=row.trade_ref, registered_at=row.registered_at)
            trades.append(value)
            raw.append(
                {
                    "ref": row.trade_ref,
                    "at": row.registered_at,
                    "quotes": row.quotes,
                    "risk": row.risk_row,
                    "mark_gap": row.mark_gap,
                    "error": row.evidence_error,
                }
            )
        evidence_digest = digest(
            {
                "binding": campaign.binding_hash,
                "final": campaign.final_run,
                "revision": campaign.revision,
                "trades": raw,
                "drawdown": campaign.max_drawdown_pct,
                "risk_breach": campaign.risk_breach,
            }
        )
        return {
            "id": campaign.id,
            "strategy_id": campaign.strategy_id,
            "final_run_id": campaign.final_run_id,
            "binding_hash": campaign.binding_hash,
            "binding": campaign.binding,
            "final_run": campaign.final_run,
            "created_at": campaign.created_at,
            "revision": campaign.revision,
            "evidence_digest": evidence_digest,
            "status": "collecting" if campaign.active_key else "superseded",
            "max_drawdown_pct": campaign.max_drawdown_pct,
            "risk_breach": campaign.risk_breach,
            "marks_complete": bool(rows) and all(r.risk_row and not r.mark_gap for r in rows),
            "source_current": self._sources_current(db, campaign, rows),
            "approval": campaign.approval,
            "reconciliation": campaign.reconciliation,
            "trades": trades,
        }

    def _sources_current(self, db, campaign, rows):
        if not rows:
            return True
        from database.trading_risk_db import RiskTrade

        # Same database transaction as the campaign snapshot: a missed terminal
        # callback cannot leave yesterday's release accepted after today's fill.
        source = dict(
            db.execute(
                select(RiskTrade.ref, RiskTrade.evidence)
                .where(
                    RiskTrade.scope == f"{campaign.owner}|sandbox",
                    RiskTrade.strategy_id == campaign.strategy_id,
                    RiskTrade.ref.in_([row.trade_ref for row in rows]),
                )
                .limit(MAX_TRADES + 1)
                .with_for_update()
            ).all()
        )
        return all(
            row.risk_row
            and row.trade_ref in source
            and row.risk_row.get("ledger_revision")
            == (source[row.trade_ref] or {}).get("_ledger_revision", 0)
            for row in rows
        )

    def get_campaign(self, owner, campaign_id):
        with self.transaction() as db:
            return self._snapshot(db, self._campaign(db, owner, campaign_id))

    def list_campaigns(self, owner):
        with self.transaction() as db:
            rows = db.scalars(
                select(QualificationCampaign)
                .where(QualificationCampaign.owner == owner)
                .order_by(QualificationCampaign.id.desc())
                .limit(MAX_CAMPAIGNS)
            ).all()
            return [self._snapshot(db, c) for c in rows]

    def active_campaign(self, owner, strategy_id):
        with self.transaction() as db:
            row = db.scalar(
                select(QualificationCampaign)
                .where(QualificationCampaign.active_key == digest([owner, strategy_id]))
                .with_for_update()
            )
            return self._snapshot(db, row)

    def create_campaign(self, owner, strategy_id, final_run_id, binding, final_run, now):
        with self.transaction() as db:
            existing = db.scalar(
                select(QualificationCampaign).where(
                    QualificationCampaign.owner == owner,
                    QualificationCampaign.strategy_id == strategy_id,
                    QualificationCampaign.binding_hash == binding["binding_hash"],
                )
            )
            if existing:
                raise ValueError(
                    "This configuration already has a campaign. Continue its complete evidence history."
                )
            count = db.scalar(
                select(func.count())
                .select_from(QualificationCampaign)
                .where(QualificationCampaign.owner == owner)
            )
            if count >= MAX_CAMPAIGNS:
                raise ValueError(
                    "Campaign storage limit reached; archive this deployment before enrolling more"
                )
            active = db.scalar(
                select(QualificationCampaign)
                .where(QualificationCampaign.active_key == digest([owner, strategy_id]))
                .with_for_update()
            )
            if active:
                active.active_key = None
                self._changed(active)
                self._audit(
                    db, active, "superseded", {"reason": "A new configuration was enrolled."}, now
                )
                db.flush()
            row = QualificationCampaign(
                owner=owner,
                strategy_id=strategy_id,
                final_run_id=final_run_id,
                active_key=digest([owner, strategy_id]),
                binding_hash=binding["binding_hash"],
                binding=bounded(binding),
                final_run=bounded(final_run),
                created_at=iso(now),
                revision=0,
                max_drawdown_pct=0,
                peak_equity=10000,
                risk_breach=False,
            )
            db.add(row)
            db.flush()
            self._audit(
                db,
                row,
                "enrolled",
                {"final_run_id": final_run_id, "binding_hash": row.binding_hash},
                now,
            )
            return self._snapshot(db, row)

    def get_registration(self, owner, trade_ref):
        with self.transaction() as db:
            row = db.get(QualificationTrade, (owner, trade_ref))
            if not row:
                return None
            campaign = self._campaign(db, owner, row.campaign_id)
            return {
                "campaign_id": row.campaign_id,
                "trade_ref": row.trade_ref,
                "registered_at": row.registered_at,
                "binding_hash": campaign.binding_hash,
            }

    def register_entry(self, owner, strategy_id, trade_ref, binding, now):
        if not isinstance(trade_ref, str) or not trade_ref or len(trade_ref) > 64:
            raise ValueError("A valid prospective trade reference is required")
        with self.transaction() as db:
            campaign = db.scalar(
                select(QualificationCampaign)
                .where(QualificationCampaign.active_key == digest([owner, strategy_id]))
                .with_for_update()
            )
            if not campaign:
                return None
            if binding["binding_hash"] != campaign.binding_hash:
                raise ValueError(
                    "Strategy configuration changed. Enroll its new forward campaign before trading."
                )
            row = db.get(QualificationTrade, (owner, trade_ref))
            if row and row.campaign_id != campaign.id:
                raise ValueError("This trade reference already belongs to another campaign")
            if not row:
                count = db.scalar(
                    select(func.count())
                    .select_from(QualificationTrade)
                    .where(QualificationTrade.campaign_id == campaign.id)
                )
                if count >= MAX_TRADES:
                    raise ValueError("Campaign trade limit reached; archive this deployment")
                row = QualificationTrade(
                    owner=owner,
                    trade_ref=trade_ref,
                    campaign_id=campaign.id,
                    registered_at=iso(now),
                    quotes={},
                    mark_gap=False,
                )
                db.add(row)
                self._changed(campaign)
            return {
                "campaign_id": campaign.id,
                "trade_ref": row.trade_ref,
                "registered_at": row.registered_at,
                "binding_hash": campaign.binding_hash,
            }

    def record_quote(self, owner, trade_ref, order_id, quote, now):
        with self.transaction() as db:
            row = db.get(QualificationTrade, (owner, trade_ref))
            if not row:
                return False
            campaign = self._campaign(db, owner, row.campaign_id)
            db.refresh(row)  # Campaign lock also serializes updates to its trades.
            key = str(order_id)
            try:
                clean = bounded(quote)
                captured = timestamp(clean.get("captured_at"))
                if not timestamp(row.registered_at) <= captured <= now:
                    raise ValueError("The quote was not captured during this registered trade")
                if len(row.quotes) >= 64 and key not in row.quotes:
                    raise ValueError("The order quote receipt limit was reached")
                if key in row.quotes and row.quotes[key] != clean:
                    raise ValueError("An immutable order quote receipt was changed")
                if row.quotes.get(key) == clean:
                    return True
                row.quotes = row.quotes | {key: clean}
            except (ValueError, TypeError, KeyError):
                row.evidence_error = "Order quote evidence could not be preserved before execution."
                self._changed(campaign)
                return False
            self._changed(campaign)
            return True

    def record_trade(self, owner, trade_ref, risk_row, now):
        with self.transaction() as db:
            row = db.get(QualificationTrade, (owner, trade_ref))
            if not row:
                return False
            campaign = self._campaign(db, owner, row.campaign_id)
            db.refresh(row)
            try:
                clean = bounded(risk_row)
                clean.pop("_observed_at", None)
                if (
                    clean.get("scope") != f"{owner}|sandbox"
                    or clean.get("ref") != trade_ref
                    or clean.get("strategy_id") != campaign.strategy_id
                    or clean.get("broker") not in {"sandbox", campaign.binding["broker"]}
                ):
                    raise ValueError("The ledger row belongs to another strategy or account")
                prior = {
                    key: value
                    for key, value in (row.risk_row or {}).items()
                    if key != "_observed_at"
                }
                if clean == prior:
                    return True
                incoming_revision = clean.get("ledger_revision")
                if type(incoming_revision) is not int or incoming_revision < 0:
                    raise ValueError("The durable ledger revision is missing")
                previous_revision = prior.get("ledger_revision", -1)
                if incoming_revision < previous_revision:
                    # Delivery can be reordered. Preserve a newly observed
                    # historical low without restoring obsolete fill prices.
                    old_drawdown, old_breach = campaign.max_drawdown_pct, campaign.risk_breach
                    self._observe_account(campaign, row, clean)
                    historical = evaluate_trade(
                        clean | {"_observed_at": iso(now)},
                        row.quotes,
                        campaign.binding,
                        row.registered_at,
                    )["marked_net"]
                    if historical is not None:
                        total = db.scalar(
                            select(func.coalesce(func.sum(QualificationTrade.marked_net), 0)).where(
                                QualificationTrade.campaign_id == campaign.id
                            )
                        )
                        equity = 10000 + total - row.marked_net + historical
                        campaign.max_drawdown_pct = max(
                            campaign.max_drawdown_pct,
                            max(0, (campaign.peak_equity - equity) / campaign.peak_equity * 100),
                        )
                    if (
                        old_drawdown != campaign.max_drawdown_pct
                        or old_breach != campaign.risk_breach
                    ):
                        self._changed(campaign)
                    return False
                if incoming_revision == previous_revision and {
                    k: v for k, v in clean.items() if k != "budget_snapshot"
                } != {k: v for k, v in prior.items() if k != "budget_snapshot"}:
                    raise ValueError("Conflicting evidence claims the same durable ledger revision")
                clean["_observed_at"] = (
                    row.risk_row["_observed_at"]
                    if incoming_revision == previous_revision
                    else iso(now)
                )
                old_orders = {
                    str(o.get("id")): o
                    for o in (row.risk_row or {}).get("evidence", {}).get("orders", [])
                }
                new_orders = {
                    str(o.get("id")): o for o in clean.get("evidence", {}).get("orders", [])
                }
                if any(
                    k not in new_orders
                    or Decimal(str(new_orders[k].get("filled_qty") or 0))
                    < Decimal(str(o.get("filled_qty") or 0))
                    for k, o in old_orders.items()
                ):
                    row.evidence_error = "Cumulative fills were removed or reduced; the evidence requires a new campaign."
                self._observe_account(campaign, row, clean)
                row.risk_row = clean
                mark = evaluate_trade(clean, row.quotes, campaign.binding, row.registered_at)[
                    "marked_net"
                ]
                if mark is None:
                    row.mark_gap = True
                else:
                    row.marked_net = mark
                    db.flush()
                    # Attribute the equity curve only to this campaign, so
                    # unrelated strategies cannot conceal its drawdown.
                    total = db.scalar(
                        select(func.coalesce(func.sum(QualificationTrade.marked_net), 0)).where(
                            QualificationTrade.campaign_id == campaign.id
                        )
                    )
                    equity = 10000 + total
                    campaign.peak_equity = max(campaign.peak_equity, equity)
                    campaign.max_drawdown_pct = max(
                        campaign.max_drawdown_pct,
                        max(0, (campaign.peak_equity - equity) / campaign.peak_equity * 100),
                    )
            except (ValueError, TypeError, KeyError, ArithmeticError):
                row.evidence_error = (
                    "The durable risk evidence is incomplete or does not belong to this campaign."
                )
            self._changed(campaign)
            return True

    def _observe_account(self, campaign, row, clean):
        snapshot = clean.get("budget_snapshot") or clean.get("evidence", {}).get("budget_snapshot")
        try:
            equity = Decimal(str(snapshot["equity"]))
            peak = Decimal(str(snapshot.get("peak_equity", snapshot.get("peak"))))
            if not equity.is_finite() or not peak.is_finite() or peak <= 0:
                raise ValueError("Missing equity")
            campaign.max_drawdown_pct = max(
                campaign.max_drawdown_pct, float(max(Decimal(0), (peak - equity) / peak * 100))
            )
            campaign.risk_breach = campaign.risk_breach or bool(
                snapshot.get("paused")
                or snapshot.get("exit_all")
                or snapshot.get("exit_buckets")
                or clean.get("risk_breach")
            )
        except (ValueError, TypeError, KeyError, ArithmeticError):
            row.mark_gap = True

    def _review_snapshot(self, db, owner, campaign_id, revision, evidence_digest):
        campaign = self._campaign(db, owner, campaign_id)
        if not campaign:
            raise LookupError("Qualification campaign not found")
        current = self._snapshot(db, campaign)
        if (
            not campaign.active_key
            or campaign.revision != revision
            or current["evidence_digest"] != evidence_digest
        ):
            raise ValueError("Campaign evidence changed. Review its latest evidence again.")
        if not current["source_current"]:
            raise ValueError(
                "The campaign is missing a durable ledger update. Reconcile again to recover it."
            )
        return campaign, current

    def reconcile(self, owner, campaign_id, revision, evidence_digest, reason, now):
        with self.transaction() as db:
            campaign, _ = self._review_snapshot(db, owner, campaign_id, revision, evidence_digest)
            campaign.reconciliation = {
                "status": "current",
                "at": iso(now),
                "reason": reason,
                "costs_confirmed": True,
                "revision": revision,
                "evidence_digest": evidence_digest,
            }
            self._audit(db, campaign, "reconciled", campaign.reconciliation, now)
            return self._snapshot(db, campaign)

    def approve(self, owner, campaign_id, revision, evidence_digest, binding, reason, now):
        with self.transaction() as db:
            campaign, current = self._review_snapshot(
                db, owner, campaign_id, revision, evidence_digest
            )
            review = campaign.reconciliation
            if (
                not review
                or review.get("status") != "current"
                or review.get("evidence_digest") != evidence_digest
            ):
                raise ValueError(
                    "Reconcile the latest campaign evidence before approving live use."
                )
            if binding["binding_hash"] != campaign.binding_hash or binding.get("risk_paused"):
                raise ValueError(
                    "The strategy configuration or current capital state no longer matches the review."
                )
            # Enforce eligibility at the durable seam as well as the service. A
            # caller cannot bypass thresholds by reaching the store directly.
            from services.risk.qualification import evaluate_campaign

            qualification = evaluate_campaign(
                campaign.final_run,
                current["trades"],
                max_drawdown_pct=campaign.max_drawdown_pct,
                marks_complete=current["marks_complete"],
                risk_breach=campaign.risk_breach,
            )
            if not qualification["eligible"]:
                raise ValueError("The campaign has not met every forward qualification check.")
            campaign.approval = {
                "status": "approved",
                "at": iso(now),
                "expires_at": iso(now + timedelta(days=POLICY["approval_days"])),
                "reason": reason,
                "revision": revision,
                "evidence_digest": evidence_digest,
                "binding_hash": binding["binding_hash"],
                "broker_epoch": binding["broker_epoch"],
                "policy_version": POLICY["version"],
            }
            self._audit(db, campaign, "approved", campaign.approval, now)
            return self._snapshot(db, campaign)

    def revoke(self, owner, campaign_id, reason, now):
        with self.transaction() as db:
            campaign = self._campaign(db, owner, campaign_id)
            if not campaign:
                raise LookupError("Qualification campaign not found")
            if campaign.approval and campaign.approval.get("status") == "revoked":
                return self._snapshot(db, campaign)
            campaign.approval = (campaign.approval or {}) | {
                "status": "revoked",
                "revoked_at": iso(now),
                "reason": reason,
            }
            self._audit(db, campaign, "revoked", campaign.approval, now)
            return self._snapshot(db, campaign)


_default_store = None


def get_store():
    global _default_store
    if _default_store is None:
        _default_store = QualificationStore()
    return _default_store


def init_db():
    get_store().init_db()
