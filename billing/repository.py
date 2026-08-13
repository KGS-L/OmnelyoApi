"""Persistance SQLite temporaire, derrière un contrat remplaçable par PostgreSQL."""
import json
import uuid
from datetime import datetime, timezone

from billing.models import PaymentStatus, Plan, ProductType, ProviderEvent
from db.database import get_connection


class BillingRepository:
    def get_plan(self, code: str) -> Plan | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM billing_plans WHERE code = ? AND active = 1", (code,)
            ).fetchone()
        if not row:
            return None
        return Plan(
            code=row["code"],
            name=row["name"],
            product_type=ProductType(row["product_type"]),
            price_minor=row["price_minor"],
            currency=row["currency"],
            credits=row["credits"],
            interval=row["billing_interval"],
            active=bool(row["active"]),
        )

    def create_payment(
        self, workspace_id: str, plan: Plan, provider: str, customer_email: str
    ) -> str:
        payment_id = str(uuid.uuid4())
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO billing_payments "
                "(id, workspace_id, plan_code, provider, customer_email, amount_minor, currency) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    payment_id,
                    workspace_id,
                    plan.code,
                    provider,
                    customer_email.lower(),
                    plan.price_minor,
                    plan.currency,
                ),
            )
            conn.commit()
        return payment_id

    def set_external_reference(self, payment_id: str, external_reference: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE billing_payments SET external_reference = ?, updated_at = datetime('now') "
                "WHERE id = ? AND status = 'pending'",
                (external_reference, payment_id),
            )
            conn.commit()

    def settle_payment(
        self,
        payment_id: str,
        provider_reference: str,
        expected_provider: str | None = None,
    ) -> bool:
        """Marque payé et accorde le produit dans une transaction idempotente."""
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = self._settle_in_connection(
                conn, payment_id, provider_reference, expected_provider
            )
            conn.commit()
            return changed

    def record_event(self, event: ProviderEvent) -> bool:
        """Retourne False si le webhook a déjà été traité."""
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO billing_events "
                "(provider, event_id, event_type, payload_json) VALUES (?, ?, ?, ?)",
                (event.provider, event.event_id, event.event_type, json.dumps(event.raw)),
            )
            conn.commit()
            return cursor.rowcount == 1

    def apply_provider_event(self, event: ProviderEvent) -> bool:
        """Enregistre et applique un succès dans une seule transaction atomique."""
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT 1 FROM billing_events WHERE provider = ? AND event_id = ?",
                (event.provider, event.event_id),
            ).fetchone()
            if existing:
                conn.commit()
                return False
            payment = conn.execute(
                "SELECT id, amount_minor, currency FROM billing_payments "
                "WHERE provider = ? AND external_reference = ?",
                (event.provider, event.external_reference),
            ).fetchone()
            if not payment:
                raise ValueError("Le webhook ne correspond à aucun paiement.")
            if event.amount_minor is not None and event.amount_minor != payment["amount_minor"]:
                raise ValueError("Le montant du webhook ne correspond pas au paiement.")
            if event.currency and event.currency.upper() != payment["currency"].upper():
                raise ValueError("La devise du webhook ne correspond pas au paiement.")
            if event.event_type == "payment.succeeded":
                self._settle_in_connection(conn, payment["id"], event.external_reference)
            conn.execute(
                "INSERT INTO billing_events (provider, event_id, event_type, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (event.provider, event.event_id, event.event_type, json.dumps(event.raw)),
            )
            conn.commit()
            return True

    def _settle_in_connection(
        self,
        conn,
        payment_id: str,
        provider_reference: str,
        expected_provider: str | None = None,
    ) -> bool:
        payment = conn.execute(
            "SELECT p.*, bp.product_type, bp.credits, bp.billing_interval "
            "FROM billing_payments p JOIN billing_plans bp ON bp.code = p.plan_code "
            "WHERE p.id = ?",
            (payment_id,),
        ).fetchone()
        if not payment:
            raise ValueError("Paiement introuvable.")
        if expected_provider and payment["provider"] != expected_provider:
            raise ValueError("Le paiement n'appartient pas au fournisseur attendu.")
        if payment["status"] == PaymentStatus.PAID:
            return False
        if payment["status"] != PaymentStatus.PENDING:
            raise ValueError(f"Paiement non payable : {payment['status']}")
        duplicate_reference = conn.execute(
            "SELECT id FROM billing_payments WHERE provider = ? AND provider_reference = ? "
            "AND id != ? LIMIT 1",
            (payment["provider"], provider_reference, payment_id),
        ).fetchone()
        if duplicate_reference:
            raise ValueError("Cette référence de transaction a déjà été utilisée.")
        conn.execute(
            "UPDATE billing_payments SET status = 'paid', provider_reference = ?, "
            "paid_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (provider_reference, payment_id),
        )
        if payment["product_type"] == ProductType.CREDITS:
            conn.execute(
                "INSERT INTO credit_ledger "
                "(workspace_id, amount, reason, payment_id) VALUES (?, ?, 'purchase', ?)",
                (payment["workspace_id"], payment["credits"], payment_id),
            )
        else:
            now = datetime.now(timezone.utc)
            conn.execute(
                "INSERT INTO subscriptions "
                "(workspace_id, plan_code, provider, external_reference, status, started_at) "
                "VALUES (?, ?, ?, ?, 'active', ?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET plan_code = excluded.plan_code, "
                "provider = excluded.provider, external_reference = excluded.external_reference, "
                "status = 'active', started_at = excluded.started_at, updated_at = datetime('now')",
                (
                    payment["workspace_id"], payment["plan_code"], payment["provider"],
                    provider_reference, now.isoformat(),
                ),
            )
        return True

    def find_payment_id(self, provider: str, external_reference: str) -> str | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM billing_payments WHERE provider = ? "
                "AND external_reference = ?",
                (provider, external_reference),
            ).fetchone()
        return row["id"] if row else None

    def credit_balance(self, workspace_id: str) -> int:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS balance FROM credit_ledger "
                "WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        return row["balance"]
