"""Probe Panasonic AC (category 0900) endpoints for new AirconCommon-* subtypes.

Usage:
    PMS_USER='phone' PMS_PASS='password' python3 tools/probe_ac_endpoints.py --report

By default only devices whose deviceId contains "CS-J13" are probed (see
--device-filter).

The official web control page does not yet support the "AirconCommon-2024-03"
subtype ("本版本不支持该家电"), so the App uses a newer protocol than the
ducted-AC profile's ACDevGetStatusInfoAW endpoint. This tool:

  1. Logs in and lists devices.
  2. Dumps each AC device's raw ``params`` from UsrGetBindDevInfo (redacted),
     which often contains statusAll field names and the devSubTypeId.
  3. Probes a list of candidate GET endpoints (AC web request shape) and
     reports which return a non-empty ``results`` payload.
  4. ``--watch`` polls the full status bean (via the working GET endpoint)
     while you toggle features in the official phone App and prints every
     field change, mapping App actions to the fields they write.

Feature endpoint shapes (electricity, mode temp, timers, ...) come from the
web control page's JS (get_device_web_url.py generates the page URL); only
the status GET endpoint needs live probing, because the web page does not
support the AirconCommon-2024-03 subtype.

If none of the candidates match, capture the phone App's HTTPS traffic to find
the exact endpoint, payload shape, and field mapping.

Verified protocol facts (0900/AirconCommon-2024-03, do not re-probe):
- GET endpoint ACDevGetStatusInfoAW (id 100); SET endpoint
  ACDevSetStatusNewProtocol (id 200, params = PARAMS bean, no-op safe).
- runMode/windSet/portraitWindSet/orientationWindSet are int codes
  (65/66/67/68/69, 49/50/52/54/55/65, 65/68/67/69/66+70,
  66/108/67/87/65+64). runStatus 48=on/49=off. ervMode 64=off/66=on,
  ervWind 1/2/3. All 0/1 feature toggles are normal polarity except lamp
  (0=on); buzzer is read-only.
- ERV only starts on partial writes: a payload carrying runStatus stores
  ervMode but never starts the motor. Use single-field writes.
- Fresh-air running state (App-verified): the ERV runs standalone with the
  AC off (ervCheck=1) or together with the AC (runStatus on + ervMode=66);
  when the AC turns off the ERV stops but the cloud keeps the stale
  ervMode=66, so the App shows the fresh air off in that state.
- buzzer is a per-request beep flag, not a setting: every App command
  carries buzzer=65 ('A') to beep; the status bean's sticky buzzer=1 is the
  unit's own beep setting, echoed back but never sent as a control value.

Requires ``aiohttp``:  python3 -m pip install aiohttp
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[1]
TLS_PATH = REPO_ROOT / "custom_components" / "panasonic_smart_china" / "tls.py"

_TLS_SPEC = importlib.util.spec_from_file_location("panasonic_tls", TLS_PATH)
if _TLS_SPEC is None or _TLS_SPEC.loader is None:
    raise RuntimeError(f"Unable to load TLS helper from {TLS_PATH}")
_TLS_MODULE = importlib.util.module_from_spec(_TLS_SPEC)
_TLS_SPEC.loader.exec_module(_TLS_MODULE)
psmartcloud_fingerprint = _TLS_MODULE.psmartcloud_fingerprint

BASE_URL = "https://app.psmartcloud.com/App/"
URL_GET_TOKEN = BASE_URL + "UsrGetToken"
URL_LOGIN = BASE_URL + "UsrLogin"
URL_GET_DEV = BASE_URL + "UsrGetBindDevInfo"

AC_CATEGORY = "0900"

# Candidate GET endpoints (dedup, keep order). Extend freely.
GET_ENDPOINTS = (
    "ACDevGetStatusInfoAW",
    "ACDevGetStatusAW",
    "ACDevGetStatusInfoAirconCommon",
    "ACDevGetStatusAirconCommon",
    "ACDevGetStatusInfoAirconCommon202403",
    "ACDevGetStatusAirconCommon202403",
    "ACDevGetStatusInfoAirconCommon2024",
    "ACDevGetStatusAirconCommon2024",
    "ACDevGetStatusInfoAircon",
    "ACDevGetStatusAircon",
    "ACDevGetStatusInfo",
    "ACDevGetStatus",
    "ADevGetStatusAirconCommon",
    "ADevGetStatusAircon",
)

SENSITIVE_KEYS = {
    "deviceid", "devid", "devicename", "devname", "deviceuuid", "mac",
    "devicemac", "sn", "devicesn", "usrid", "userid", "ssid", "token",
    "password", "pwd", "tel", "mobile", "familyid", "realfamilyid",
}
DEVICE_ID_RE = re.compile(r"\b[0-9a-f]{12}_\d{4}_[a-z0-9.-]+\b", re.IGNORECASE)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if re.sub(r"[^a-z0-9]", "", str(key).lower()) in SENSITIVE_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return DEVICE_ID_RE.sub(
            lambda m: f"<device:{hashlib.sha256(m.group(0).encode()).hexdigest()[:10]}>",
            value,
        )
    return value


def device_category(device_id: str) -> str | None:
    parts = device_id.split("_")
    return parts[1] if len(parts) >= 2 else None


def device_token(device_id: str) -> str | None:
    parts = device_id.split("_")
    if len(parts) != 3:
        return None
    mac, category, suffix = parts[0].upper(), parts[1].upper(), parts[2]
    inner = hashlib.sha512(f"{mac[6:]}_{category}_{mac[:6]}".encode()).hexdigest()
    return hashlib.sha512(f"{inner}_{suffix}".encode()).hexdigest()


def base_headers(ssid: str | None = None) -> dict[str, str]:
    result = {"User-Agent": "SmartApp", "Content-Type": "application/json"}
    if ssid:
        result["Cookie"] = f"SSID={ssid}"
    return result


def control_headers(ssid: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)",
        "xtoken": f"SSID={ssid}",
        "DNT": "1",
        "Origin": "https://app.psmartcloud.com",
        "X-Requested-With": "XMLHttpRequest",
    }


async def post_json(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[int, Any]:
    async with session.post(
        url, json=payload, headers=headers, ssl=psmartcloud_fingerprint()
    ) as response:
        try:
            body = await response.json(content_type=None)
        except Exception:  # noqa: BLE001
            body = {"rawText": (await response.text())[:500]}
        return response.status, body


async def login(session, username, password):
    _, token_response = await post_json(
        session, URL_GET_TOKEN,
        {"id": 1, "uiVersion": 4.0, "params": {"usrId": username}},
        base_headers(),
    )
    token_start = token_response.get("results", {}).get("token")
    if not token_start:
        raise RuntimeError(f"GetToken failed: {redact(token_response)}")

    pwd_md5 = hashlib.md5(password.encode()).hexdigest().upper()
    inter_md5 = hashlib.md5((pwd_md5 + username).encode()).hexdigest().upper()
    final_token = hashlib.md5((inter_md5 + token_start).encode()).hexdigest().upper()

    _, login_response = await post_json(
        session, URL_LOGIN,
        {
            "id": 2, "uiVersion": 4.0,
            "params": {
                "telId": "00:00:00:00:00:00", "checkFailCount": 0,
                "usrId": username, "pwd": final_token,
            },
        },
        base_headers(),
    )
    results = login_response.get("results")
    if not isinstance(results, dict):
        raise RuntimeError(f"Login failed: {redact(login_response)}")
    return (
        results["usrId"], results["ssId"],
        results.get("familyId"), results.get("realFamilyId"),
    )


async def get_devices(session, usr_id, ssid, family_id, real_family_id):
    _, response = await post_json(
        session, URL_GET_DEV,
        {
            "id": 3, "uiVersion": 4.0,
            "params": {
                "realFamilyId": real_family_id, "familyId": family_id,
                "usrId": usr_id,
            },
        },
        base_headers(ssid),
    )
    return response.get("results", {}).get("devList", [])


async def probe_get(
    session, endpoint, device_id, usr_id, ssid, token,
    params: dict[str, Any] | None = None,
    request_ids: tuple[int, ...] = (100, 1),
) -> dict[str, Any]:
    """Probe one GET endpoint with the AC web request shape."""
    outcomes = {}
    payload = {
        "usrId": usr_id, "deviceId": device_id, "token": token,
    }
    if params is not None:
        payload["params"] = params
    for request_id in request_ids:
        try:
            status, body = await post_json(
                session, BASE_URL + endpoint,
                {"id": request_id, **payload},
                control_headers(ssid),
            )
        except Exception as err:  # noqa: BLE001
            outcomes[f"id{request_id}"] = {"status": "request_failed", "message": redact(str(err))}
            continue

        summary: dict[str, Any] = {"httpStatus": status}
        if isinstance(body, dict):
            results = body.get("results")
            if isinstance(results, dict) and results:
                summary["status"] = "ok"
                summary["fieldCount"] = len(results)
                summary["results"] = redact(results)
            elif isinstance(results, list) and results:
                summary["status"] = "ok"
                summary["itemCount"] = len(results)
                summary["results"] = redact(results)
            elif "error" in body:
                summary["status"] = "error"
                summary["error"] = redact(body["error"])
            else:
                summary["status"] = "unexpected"
                summary["response"] = redact(body)
        else:
            summary["status"] = "unexpected"
            summary["response"] = redact(body)
        outcomes[f"id{request_id}"] = summary
    return outcomes


def device_snapshot(device: dict[str, Any]) -> dict[str, Any]:
    params = device.get("params", {})
    return {
        "category": device_category(str(device.get("deviceId", ""))),
        "model": params.get("deviceMNO") or params.get("deviceModel"),
        "devSubTypeId": params.get("devSubTypeId"),
        "params": redact(params),
    }


async def probe_watch(
    session, endpoint, device_id, usr_id, ssid, token,
    seconds: int = 90, interval: float = 2.0,
) -> dict[str, Any]:
    """Poll the full status bean while the user toggles features in the App.

    Prints every field change with a timestamp so App actions can be mapped
    to the protocol fields they write. This is the general tool for
    verifying fine-grained semantics (polarity, swing positions, hidden
    helper fields) on any device.
    """
    async def get_state() -> dict | None:
        result = await probe_get(
            session, endpoint, device_id, usr_id, ssid, token
        )
        for v in result.values():
            if isinstance(v, dict) and v.get("status") == "ok":
                return v.get("results")
        return None

    snapshot = await get_state()
    if not snapshot:
        return {"status": "no_current_state"}
    previous = dict(snapshot)
    print(f"Watching for {seconds}s. Toggle features in the App now...")
    print("Baseline: " + json.dumps(redact(previous), ensure_ascii=False))
    changes: dict[str, Any] = {"baseline": redact(previous), "events": []}
    deadline = time.time() + seconds
    while time.time() < deadline:
        await asyncio.sleep(interval)
        state = await get_state()
        if not state:
            continue
        event = {"t": time.strftime("%H:%M:%S")}
        for key, new_value in state.items():
            if key in previous and new_value != previous.get(key):
                event[key] = {"from": previous.get(key), "to": new_value}
        if len(event) > 1:
            for key in event:
                if key != "t":
                    previous[key] = state.get(key)
            print("CHANGE " + json.dumps(event, ensure_ascii=False))
            changes["events"].append(event)
    return changes


async def run(args) -> dict[str, Any]:
    username = os.environ.get("PMS_USER")
    password = os.environ.get("PMS_PASS")
    if not username or not password:
        raise RuntimeError("Please set PMS_USER and PMS_PASS environment variables")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        print("Logging in to Panasonic Smart China...")
        usr_id, ssid, family_id, real_family_id = await login(session, username, password)
        devices = await get_devices(session, usr_id, ssid, family_id, real_family_id)
        selected = [
            d for d in devices
            if device_category(str(d.get("deviceId", ""))) == AC_CATEGORY
        ]
        if not selected:
            selected = devices
        print(f"Found {len(devices)} devices; probing {len(selected)} AC device(s).")

        if args.device_filter:
            selected = [
                d for d in selected
                if args.device_filter.lower() in str(d.get("deviceId", "")).lower()
            ]
            print(
                f"Device filter '{args.device_filter}': "
                f"{len(selected)} device(s) left."
            )

        report = {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "deviceFilter": args.device_filter,
            "devices": [],
        }
        for device in selected:
            device_id = str(device.get("deviceId", ""))
            token = device_token(device_id)
            snapshot = device_snapshot(device)
            print(
                f"[{snapshot.get('model') or '?'}] subtype="
                f"{snapshot.get('devSubTypeId') or '?'} deviceId={device_id}"
            )
            endpoint_results = {}
            if token is None:
                endpoint_results["token"] = {"status": "token_generation_failed"}
            else:
                for endpoint in GET_ENDPOINTS:
                    result = await probe_get(session, endpoint, device_id, usr_id, ssid, token)
                    endpoint_results[endpoint] = result
                    ok = any(
                        v.get("status") == "ok"
                        for v in result.values() if isinstance(v, dict)
                    )
                    fields = next(
                        (v.get("fieldCount") for v in result.values()
                         if isinstance(v, dict) and v.get("status") == "ok"),
                        0,
                    )
                    print(f"  {endpoint}: {'OK' if ok else '--'} fields={fields}")

            report_entry = {**snapshot, "endpoints": endpoint_results}

            report["devices"].append(report_entry)

            if args.watch:
                working = next(
                    (
                        ep
                        for ep, res in endpoint_results.items()
                        if any(
                            isinstance(v, dict) and v.get("status") == "ok"
                            for v in res.values()
                        )
                    ),
                    "ACDevGetStatusInfoAW",
                )
                print(
                    f"  --- WATCH ALL FIELDS via {working} "
                    "(toggle the feature in the App now) ---"
                )
                result = await probe_watch(
                    session, working, device_id, usr_id, ssid, token,
                    seconds=args.watch,
                )
                report_entry["watch"] = result
                break  # only watch the first device
        return report


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", nargs="?", const="", help="Write a redacted JSON report")
    parser.add_argument(
        "--device-filter",
        default="CS-J13",
        help="Only probe devices whose deviceId contains this substring "
             "(default: CS-J13)",
    )
    parser.add_argument(
        "--watch",
        type=int,
        nargs="?",
        const=90,
        metavar="SECONDS",
        help="Poll the full status bean while you toggle features in the "
             "official App; prints every field change (default 90s)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(run(args))
    except Exception as err:  # noqa: BLE001
        print(f"Error: {err}", file=sys.stderr)
        return 1
    if args.report is not None:
        path = Path(args.report) if args.report else Path(
            f"ac_endpoint_report_{time.strftime('%Y%m%d-%H%M%S')}.json"
        )
        path.write_text(
            json.dumps(redact(report), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"Redacted report written to {path}")
    else:
        print(json.dumps(redact(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())