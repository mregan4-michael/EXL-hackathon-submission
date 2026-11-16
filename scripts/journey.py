#!/usr/bin/env python3
"""Claims Workbench core journey against a running generated API (offline or Compose).

intake -> triage -> settlement -> payment authorisation, plus two refusals:
an Auditor (no Create privilege, 403) and a handler above their authority limit (409,
the legacy button guard re-evaluated server-side). Exits non-zero on any unexpected
result. Stdlib only, so it runs anywhere Python 3.10+ does.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

BASE = os.environ.get("API_URL", "http://localhost:8080")
if not BASE.startswith(("http://", "https://")):
    raise SystemExit(f"API_URL must be http(s): {BASE}")
HANDLER = "hana.handler@example.test"
AUDITOR = "ari.auditor@example.test"
SUB = "IntakeScreen/btnSubmit"
APP = "SettlementScreen/btnApprovePayment"
failures: list[str] = []
# Each check names the legacy source paths it exercises; `--record FILE` saves them as
# scenario evidence for `factory parity` (rules with no executed oracle evidence).
checks: list[dict[str, Any]] = []


def call(user: str | None, path: str, body: Any = None) -> tuple[int, Any, str]:
    cid = str(uuid.uuid4())
    req = urllib.request.Request(  # noqa: S310 (scheme checked above)
        BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Correlation-ID": cid}
        | ({"X-Demo-User": user} if user else {}),
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return r.status, json.loads(r.read() or b"null"), cid
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None, cid


def check(name: str, ok: bool, detail: str, paths: tuple[str, ...] = ()) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    checks.append({"name": name, "ok": ok, "paths": list(paths)})
    if not ok:
        failures.append(name)


INTAKE = {
    "txtPolicyNumber.Text": "PL12345678",
    "txtClaimAmount.Text": "3200",
    "dpIncidentDate.SelectedDate": "2026-11-01",
    "dpNotifiedDate.SelectedDate": "2026-11-03",
    "dpPolicyStart.SelectedDate": "2026-01-01",
    "dpPolicyEnd.SelectedDate": "2026-12-31",
    "ddClaimType.Selected.Value": "Motor",
}
TRIAGE = {"txtPriorClaims.Text": "0", "chkNoPoliceRef.Value": False, "chkVulnerable.Value": False}
SETTLE = {
    "txtPartsCost.Text": "1200",
    "txtVehicleAge.Text": "3",
    "chkVatRegistered.Value": False,
    "txtPayeeSortCode.Text": "12-34-56",
}


def evaluate(user: str, screen: str, inputs: dict[str, Any]) -> dict[str, Any]:
    status, body, _ = call(user, f"/api/screens/{screen}/evaluate", {"inputs": inputs})
    if status != 200:
        raise SystemExit(f"evaluate {screen} -> {status} {body}")
    return dict(body["values"])


def main() -> int:
    print(f"Core journey against {BASE}")
    status, health, _ = call(None, "/health")
    check("health", status == 200, json.dumps(health))

    print("1. Intake (IntakeScreen)")
    incomplete = evaluate(HANDLER, "IntakeScreen", {**INTAKE, "txtPolicyNumber.Text": ""})
    check(
        "submit disabled without policy number (BR-011)",
        incomplete.get("btnSubmit.DisplayMode") == "Disabled",
        str(incomplete.get("btnSubmit.DisplayMode")),
        (f"{SUB}.DisplayMode",),
    )
    v = evaluate(HANDLER, "IntakeScreen", INTAKE)
    check(
        "submit enabled for complete claim (BR-011)",
        v.get("btnSubmit.DisplayMode") == "Edit",
        str(v.get("btnSubmit.DisplayMode")),
        (f"{SUB}.DisplayMode",),
    )
    ctx = {"clm_NotifiedDate": "2026-11-03", "clm_ClaimType": "Motor", "clm_CustomerId": "cust-001"}
    status, body, cid = call(
        HANDLER, "/api/screens/IntakeScreen/actions/btnSubmit", {"inputs": INTAKE, "context": ctx}
    )
    claim_id = (body or {}).get("record", {}).get("id")
    check(
        "ClaimsHandler creates claim",
        status == 200 and claim_id is not None,
        f"{status} id={claim_id} status={(body or {}).get('record', {}).get('clm_Status')} "
        f"next={(body or {}).get('navigateTo')} correlation={cid}",
        (f"{SUB}.OnSelect",),
    )

    status, body, cid = call(
        AUDITOR, "/api/screens/IntakeScreen/actions/btnSubmit", {"inputs": INTAKE, "context": ctx}
    )
    check(
        "Auditor refused claim creation (no prvCreate)",
        status == 403,
        f"{status} {(body or {}).get('detail')} correlation={cid}",
        (f"{SUB}.OnSelect", "Auditor"),
    )

    print("2. Triage (TriageScreen)")
    t = evaluate(HANDLER, "TriageScreen", {**INTAKE, **TRIAGE})
    for k in (
        "lblFraudScore.Text",
        "lblFraudReferral.Visible",
        "lblPriority.Text",
        "lblSlaDays.Text",
        "lblAuthority.Text",
        "lblFourEyes.Visible",
    ):
        print(f"       {k} = {t.get(k)!r}")
    check(
        "triage rules evaluated",
        "lblFraudScore.Text" in t and "lblPriority.Text" in t,
        "fraud score + priority present",
    )

    print("3. Settlement (SettlementScreen)")
    s = evaluate(HANDLER, "SettlementScreen", {**INTAKE, **TRIAGE, **SETTLE})
    for k in (
        "lblExcess.Text",
        "lblBetterment.Text",
        "lblVatRecoverable.Text",
        "lblNetSettlement.Text",
        "lblSortCodeError.Text",
        "btnApprovePayment.DisplayMode",
    ):
        print(f"       {k} = {s.get(k)!r}")
    check(
        "approve enabled within authority limit (BR-017)",
        s.get("btnApprovePayment.DisplayMode") == "Edit",
        f"{s.get('btnApprovePayment.DisplayMode')} (limit 5000, claim 3200)",
        (f"{APP}.DisplayMode", "App.OnStart"),
    )

    print("4. Payment authorisation")
    pctx = {"clm_ClaimId": claim_id, "clm_AccountNumber": "00012345"}
    status, body, cid = call(
        HANDLER,
        "/api/screens/SettlementScreen/actions/btnApprovePayment",
        {"inputs": {**INTAKE, **TRIAGE, **SETTLE}, "context": pctx},
    )
    rec = (body or {}).get("record", {})
    check(
        "payment created by handler",
        status == 200,
        f"{status} amount={rec.get('clm_Amount')} approvedBy={rec.get('clm_ApprovedBy')}"
        f" correlation={cid}",
        (f"{APP}.OnSelect",),
    )

    big = {**INTAKE, **TRIAGE, **SETTLE, "txtClaimAmount.Text": "18500"}
    status, body, cid = call(
        HANDLER,
        "/api/screens/SettlementScreen/actions/btnApprovePayment",
        {"inputs": big, "context": pctx},
    )
    check(
        "over-authority payment refused (guard re-evaluated server-side)",
        status == 409,
        f"{status} {(body or {}).get('detail')} correlation={cid}",
        (f"{APP}.DisplayMode", f"{APP}.OnSelect", "App.OnStart"),
    )
    status, body, cid = call(
        AUDITOR,
        "/api/screens/SettlementScreen/actions/btnApprovePayment",
        {"inputs": {**INTAKE, **TRIAGE, **SETTLE}, "context": pctx},
    )
    check(
        "Auditor refused payment",
        status == 403,
        f"{status} {(body or {}).get('detail')}",
        (f"{APP}.OnSelect", "Auditor"),
    )

    status, rows, _ = call(AUDITOR, "/api/clm_Payments")
    check(
        "Auditor can read payments (Global read)",
        status == 200 and isinstance(rows, list),
        f"{status} rows={len(rows) if isinstance(rows, list) else rows}",
        ("Auditor",),
    )

    if "--record" in sys.argv:
        out = sys.argv[sys.argv.index("--record") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"app": "claims-workbench", "checks": checks}, f, indent=2)
            f.write("\n")
    print(f"\n{'JOURNEY PASSED' if not failures else 'JOURNEY FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
