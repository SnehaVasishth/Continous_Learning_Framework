"""One-shot backfill: walk backend/data/outputs/, upload each PDF/XLSX to
SharePoint, then stamp the resulting webUrl onto the matching Salesforce
record's URL field.

Run:
    python -m app.scripts.sharepoint_backfill --dry-run
    python -m app.scripts.sharepoint_backfill
"""
from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path

from ..db import SessionLocal
from ..models import Asset, CalibrationCert, Customer, Invoice, Order, Quote, WorkOrder
from ..services import salesforce as sf_svc
from ..services import sharepoint as sp_svc
from .sharepoint_stamp import stamp_salesforce_url, upload_to_sharepoint

log = logging.getLogger("sharepoint_backfill")

OUTPUTS_DIR = Path(__file__).resolve().parents[2] / "data" / "outputs"

# regex for embedded customer code, e.g. AURA-AUTO-119, NORDS-TELCO-045, SAKURA-SEMI-101
_CUSTOMER_CODE_RE = re.compile(r"[A-Z]+-[A-Z&]+-\d+")


def _parse_customer_code(filename: str) -> str | None:
    m = _CUSTOMER_CODE_RE.search(filename)
    return m.group(0) if m else None


def _customer_code_from_db(db, *, prefix: str, ident: str) -> str | None:
    """Fallback DB lookup when filename has no customer code embedded."""
    try:
        if prefix == "CERT":
            cert = db.query(CalibrationCert).filter_by(cert_number=ident).first()
            if cert and cert.customer_id:
                c = db.query(Customer).filter_by(id=cert.customer_id).first()
                return c.code if c else None
        elif prefix == "WO":
            wo = db.query(WorkOrder).filter_by(wo_number=ident).first()
            if wo and wo.customer_id:
                c = db.query(Customer).filter_by(id=wo.customer_id).first()
                return c.code if c else None
        elif prefix in ("QT", "BOM"):
            q = db.query(Quote).filter_by(quote_number=ident).first()
            if q and q.customer_id:
                c = db.query(Customer).filter_by(id=q.customer_id).first()
                return c.code if c else None
        elif prefix == "SO":
            o = db.query(Order).filter_by(order_number=ident).first()
            if o and o.customer_id:
                c = db.query(Customer).filter_by(id=o.customer_id).first()
                return c.code if c else None
        elif prefix == "INV":
            inv = db.query(Invoice).filter_by(invoice_number=ident).first()
            if inv and inv.customer_id:
                c = db.query(Customer).filter_by(id=inv.customer_id).first()
                return c.code if c else None
    except Exception as e:
        log.warning("DB customer lookup failed for %s/%s: %s", prefix, ident, e)
    return None


def _classify(filename: str) -> tuple[str | None, str | None, str | None]:
    """Returns (prefix, identifier, sp_subfolder_kind) or (None, None, None) to skip."""
    stem = Path(filename).stem  # strip extension
    if stem.startswith("CERT_"):
        return "CERT", stem[len("CERT_"):], "calibration"
    if stem.startswith("WO_"):
        return "WO", stem[len("WO_"):], "workorders"
    if stem.startswith("QT_"):
        return "QT", stem[len("QT_"):], "quotes"
    if stem.startswith("BOM_"):
        return "BOM", stem[len("BOM_"):], "quotes"
    if stem.startswith("SO_"):
        return "SO", stem[len("SO_"):], "orders"
    if stem.startswith("INV_"):
        return "INV", stem[len("INV_"):], "invoices"
    if stem.startswith("SOA_"):
        # SOA = Sales Order Acknowledgment. Routed to /orders alongside SO_.
        # No native SF URL field on Order; upload-only (same as SO_/INV_).
        return "SOA", stem[len("SOA_"):], "orders"
    return None, None, None


def _build_sf_caches(db) -> tuple[dict[str, str], dict[str, str]]:
    """Bulk-load SF Asset SerialNumber -> Id and WorkOrder WO_Number__c -> Id."""
    serial_to_id: dict[str, str] = {}
    wo_to_id: dict[str, str] = {}
    conn = sf_svc.get_active_connection(db)
    if not conn:
        log.warning("Salesforce not connected — caches empty")
        return serial_to_id, wo_to_id
    try:
        sf = sf_svc.client_for(conn)
        for r in sf.query_all("SELECT Id, SerialNumber FROM Asset WHERE SerialNumber != null").get("records", []):
            sn = r.get("SerialNumber")
            if sn:
                serial_to_id[sn] = r["Id"]
        for r in sf.query_all("SELECT Id, WO_Number__c FROM WorkOrder WHERE WO_Number__c != null").get("records", []):
            wn = r.get("WO_Number__c")
            if wn:
                wo_to_id[wn] = r["Id"]
    except Exception as e:
        log.warning("SF cache build failed: %s", e)
    return serial_to_id, wo_to_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill SharePoint URLs onto SF records.")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without uploading.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not OUTPUTS_DIR.exists():
        print(f"Outputs dir not found: {OUTPUTS_DIR}")
        return

    db = SessionLocal()
    scanned = uploaded = stamped = no_sf = no_field = errors = 0
    skipped_files: list[str] = []

    serial_to_id, wo_to_id = _build_sf_caches(db)

    files: list[Path] = []
    for root, _dirs, fnames in os.walk(OUTPUTS_DIR):
        for fn in fnames:
            if fn.lower().endswith((".pdf", ".xlsx")):
                files.append(Path(root) / fn)

    for fp in sorted(files):
        scanned += 1
        prefix, ident, kind = _classify(fp.name)
        if not prefix:
            skipped_files.append(f"{fp.name} (unknown prefix)")
            continue

        cust_code = _parse_customer_code(fp.name) or _customer_code_from_db(db, prefix=prefix, ident=ident)
        if not cust_code:
            skipped_files.append(f"{fp.name} (no customer code)")
            continue
        subfolder = f"{cust_code}/{kind}"

        # determine SF target (or mark "no URL field")
        sf_object: str | None = None
        sf_record_id: str | None = None
        sf_field: str | None = None
        if prefix == "CERT":
            cert = db.query(CalibrationCert).filter_by(cert_number=ident).first()
            if cert and cert.asset_id:
                asset = db.query(Asset).filter_by(id=cert.asset_id).first()
                if asset and asset.serial:
                    sf_record_id = serial_to_id.get(asset.serial)
                    if sf_record_id:
                        sf_object, sf_field = "Asset", "Cal_Cert_Url__c"
        elif prefix == "WO":
            sf_record_id = wo_to_id.get(ident)
            if sf_record_id:
                sf_object, sf_field = "WorkOrder", "Document_Url__c"
        # QT / BOM / SO / INV: upload only, no SF stamp

        action = "DRY-RUN" if args.dry_run else "UPLOAD"
        if sf_object:
            print(f"[{action}] {fp.name} -> /{subfolder}/  | stamp {sf_object}({sf_record_id}).{sf_field}")
        else:
            print(f"[{action}] {fp.name} -> /{subfolder}/  | no-stamp ({prefix})")

        if args.dry_run:
            if sf_object:
                # in dry-run, count it as if it would succeed
                pass
            else:
                no_field += 1
            continue

        up = upload_to_sharepoint(db, local_path=fp, subfolder=subfolder)
        if not up.get("ok"):
            errors += 1
            log.warning("upload failed for %s: %s", fp.name, up.get("error"))
            continue
        uploaded += 1

        if not sf_object:
            no_field += 1
            continue
        if not sf_record_id:
            no_sf += 1
            continue

        stamp = stamp_salesforce_url(
            db,
            sf_object=sf_object,
            sf_record_id=sf_record_id,
            sf_field=sf_field,
            web_url=up["sp_url"],
        )
        if stamp.get("ok"):
            stamped += 1
        else:
            errors += 1
            log.warning("stamp failed for %s: %s", fp.name, stamp.get("error"))

    db.close()

    print()
    print("=== SharePoint backfill ===")
    print(f"Files scanned:   {scanned}")
    print(f"Uploaded:        {uploaded}")
    print(f"Stamped to SF:   {stamped}")
    print(f"Skipped (no SF match): {no_sf}")
    print(f"Skipped (no URL field): {no_field}")
    print(f"Errors:          {errors}")
    if skipped_files:
        print(f"\nSkipped files ({len(skipped_files)}):")
        for s in skipped_files:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
