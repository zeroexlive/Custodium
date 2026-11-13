#!/usr/bin/env python3
"""End-to-end provisioning rehearsal (local, throwaway state).

Boots the REAL components on one machine and drives them over
HTTP, exactly as an operator rehearsing a deployment would:

  1. three `custodium-signer` node processes (distinct store dirs
     and store keys, peer-to-peer cluster transport),
  2. the Django backend (development settings, SQLite file in the
     rehearsal dir) with the signer gate OPEN for this run only,
  3. the API journey: register -> organization -> project ->
     wallet -> POST /wallets/{id}/provision (two real DKGs),
  4. independent verification of the derived addresses from the
     signer-reported group public keys (EVM via keccak/EIP-55,
     TRON via Base58Check, Solana via base58 — recomputed here,
     not via the backend's helpers; TON checked for raw form,
     its derivation being differentially verified in Phase 8),
  5. backend-initiated threshold signatures through the REAL
     dispatch factories: an ECDSA signature recovered against the
     wallet's EVM address, and an Ed25519 signature verified
     against the FROST group key.

Everything is throwaway: state lives under
~/custodium-rehearsal/<timestamp>/ and all processes are torn
down at the end. This rehearses software behaviour on one host;
it is NOT a production deployment, not a key ceremony, and it
does not change Custodium's recorded status (not Security
Reviewed / not Production Approved).

Usage (from the repo root, backend venv python):
  apps/backend/.venv/bin/python scripts/rehearse_provisioning.py
Optional env: SIGNER_BIN (default: services/mpc/target/debug/custodium-signer)
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from Crypto.Hash import keccak

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "apps" / "backend"
SIGNER_BIN = Path(
    os.environ.get(
        "SIGNER_BIN", REPO / "services" / "mpc" / "target" / "debug" / "custodium-signer"
    )
)
SIGNER_PORTS = [18611, 18612, 18613]
BACKEND_PORT = 18620
API_TOKEN = secrets.token_hex(16)
CLUSTER_TOKEN = secrets.token_hex(16)
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

processes: list[subprocess.Popen] = []


def spawn(cmd, env, log_name, cwd=None) -> subprocess.Popen:
    log = open(RUN_DIR / log_name, "ab")
    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=cwd,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    processes.append(proc)
    return proc


def wait_http(url: str, timeout_s: float = 120.0) -> None:
    deadline = time.time() + timeout_s
    with httpx.Client(trust_env=False, timeout=5.0) as client:
        while time.time() < deadline:
            try:
                if client.get(url).status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
    raise RuntimeError(f"no response from {url} within {timeout_s}s")


def b58encode(data: bytes) -> str:
    num = int.from_bytes(data, "big")
    out = ""
    while num:
        num, rem = divmod(num, 58)
        out = B58[rem] + out
    return "1" * (len(data) - len(data.lstrip(b"\x00"))) + out


def eip55(address_bytes: bytes) -> str:
    lower = address_bytes.hex()
    digest = keccak.new(digest_bits=256, data=lower.encode()).hexdigest()
    return "0x" + "".join(
        ch.upper() if int(digest[i], 16) >= 8 else ch for i, ch in enumerate(lower)
    )


def evm_bytes_from_pubkey(public_key: bytes) -> bytes:
    digest = keccak.new(digest_bits=256, data=public_key[1:]).digest()
    return digest[-20:]


def main() -> int:
    global RUN_DIR
    RUN_DIR = (
        Path.home()
        / "custodium-rehearsal"
        / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    )
    RUN_DIR.mkdir(parents=True)
    print(f"rehearsal dir: {RUN_DIR}")
    if not SIGNER_BIN.exists():
        print(f"signer binary missing: {SIGNER_BIN} (build: cargo build -p signer_service)")
        return 1
    checks: dict[str, object] = {}
    try:
        # --- 1. signer nodes -------------------------------------------------
        peer_list = ",".join(f"http://127.0.0.1:{p}" for p in SIGNER_PORTS)
        for i, port in enumerate(SIGNER_PORTS):
            store = RUN_DIR / f"node{i}"
            store.mkdir()
            key_file = store / "store.key"
            key_file.write_text(secrets.token_hex(32))
            env = dict(
                os.environ,
                SIGNER_PARTY_INDEX=str(i),
                SIGNER_PEERS=peer_list,
                SIGNER_BIND=f"127.0.0.1:{port}",
                SIGNER_STORE_DIR=str(store),
                SIGNER_STORE_KEY_FILE=str(key_file),
                SIGNER_API_TOKEN=API_TOKEN,
                SIGNER_CLUSTER_TOKEN=CLUSTER_TOKEN,
            )
            spawn([str(SIGNER_BIN)], env, f"signer-{i}.log")
        for port in SIGNER_PORTS:
            wait_http(f"http://127.0.0.1:{port}/healthz")
        print("signer nodes: 3 healthy")
        checks["signer_nodes"] = 3

        # --- 2. backend -------------------------------------------------------
        backend_env = dict(
            os.environ,
            DJANGO_SETTINGS_MODULE="config.settings.development",
            DATABASE_URL=f"sqlite:///{RUN_DIR}/rehearsal.db",
            MPC_SIGNER_ENABLED="true",
            MPC_SIGNER_URL=f"http://127.0.0.1:{SIGNER_PORTS[0]}",
            MPC_SIGNER_TOKEN=API_TOKEN,
        )
        py = sys.executable
        for cmd in (["migrate", "--noinput"], ["seed_networks_assets"]):
            done = subprocess.run(
                [py, "manage.py", *cmd],
                env=backend_env,
                cwd=BACKEND,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if done.returncode != 0:
                print(done.stdout[-2000:], done.stderr[-2000:])
                return 1
        spawn(
            [py, "manage.py", "runserver", f"127.0.0.1:{BACKEND_PORT}", "--noreload"],
            backend_env,
            "backend.log",
            cwd=BACKEND,
        )
        wait_http(f"http://127.0.0.1:{BACKEND_PORT}/healthz")
        print("backend: healthy (gate open for this rehearsal only)")
        checks["backend"] = "healthy"

        # --- 3. API journey ----------------------------------------------------
        api = httpx.Client(
            base_url=f"http://127.0.0.1:{BACKEND_PORT}/api/v1",
            trust_env=False,
            timeout=httpx.Timeout(1800.0),
        )

        def call(method: str, path: str, token: str | None = None, **kw) -> dict:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            resp = api.request(method, path, headers=headers, **kw)
            assert resp.status_code in (200, 201), (path, resp.status_code, resp.text[:400])
            return resp.json()

        user = call(
            "POST",
            "/auth/register",
            json={
                "email": "rehearsal@example.com",
                "password": "Str0ng!Passw0rd",
                "display_name": "Rehearsal",
            },
        )
        token = user["token"]
        org = call("POST", "/organizations", token, json={"name": "Rehearsal Org"})
        project = call(
            "POST",
            "/projects",
            token,
            json={
                "organization_id": org["id"],
                "name": "Rehearsal",
                "environment": "sandbox",
            },
        )
        wallet = call(
            "POST",
            "/wallets",
            token,
            json={
                "project_id": project["id"],
                "label": "Rehearsal wallet",
                "external_customer_id": "cust-rehearsal-1",
            },
        )
        assert wallet["status"] == "provisioning", wallet
        print(f"wallet created: {wallet['id']} (provisioning)")
        started = time.time()
        wallet = call("POST", f"/wallets/{wallet['id']}/provision", token)
        elapsed = round(time.time() - started, 1)
        assert wallet["status"] == "active", wallet
        refs = wallet["key_generation"]
        print(f"provisioned in {elapsed}s: {refs}")
        checks["provision_seconds"] = elapsed
        checks["key_refs"] = refs
        listing = call("GET", f"/wallets/{wallet['id']}/addresses", token)
        addresses = {item["network"]: item["address"] for item in listing["items"]}
        assert len(addresses) == 10, addresses
        checks["addresses"] = addresses

        # --- 4. independent address verification ------------------------------
        signer = httpx.Client(
            base_url=f"http://127.0.0.1:{SIGNER_PORTS[0]}",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            trust_env=False,
            timeout=30.0,
        )
        ecdsa_meta = signer.get(f"/v1/keys/{refs['ecdsa_key_ref']}").json()
        ed_meta = signer.get(f"/v1/keys/{refs['ed25519_key_ref']}").json()
        ecdsa_pub = bytes.fromhex(ecdsa_meta["public_key"])
        ed_pub = bytes.fromhex(ed_meta["public_key"])

        evm_raw = evm_bytes_from_pubkey(ecdsa_pub)
        assert addresses["ethereum"] == eip55(evm_raw), addresses["ethereum"]
        payload = b"\x41" + evm_raw
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        assert addresses["tron"] == b58encode(payload + checksum), addresses["tron"]
        assert addresses["solana"] == b58encode(ed_pub), addresses["solana"]
        ton = addresses["ton"]
        assert ton.startswith("0:") and len(ton) == 66, ton
        checks["address_verification"] = (
            "evm/tron/solana recomputed independently in the driver; "
            "ton raw-form shape only (derivation differentially verified in Phase 8)"
        )
        print("addresses verified independently (EVM/TRON/Solana)")

        # --- 5. backend-initiated threshold signatures -------------------------
        snippet = (
            "import hashlib, json\n"
            "from waas.modules.wallets.models import Wallet\n"
            "from waas.modules.operations.dispatch import default_ecdsa_signer, default_ed25519_signer\n"
            "from waas.modules.evm.keys import find_recovery_id, recover_address\n"
            f"w = Wallet.objects.get(id='{wallet['id']}')\n"
            "es = default_ecdsa_signer()\n"
            "digest = hashlib.sha256(b'custodium provisioning rehearsal').digest()\n"
            "r, s = es.sign_digest(w, digest)\n"
            "v = find_recovery_id(digest, r, s, es.wallet_public_key(w))\n"
            "recovered = recover_address(digest, r, s, v)\n"
            "fs = default_ed25519_signer()\n"
            "msg = b'custodium provisioning rehearsal'\n"
            "sig = fs.sign_message(w, msg)\n"
            "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey\n"
            "Ed25519PublicKey.from_public_bytes(fs.wallet_public_key(w)).verify(sig, msg)\n"
            "print('REHEARSAL_JSON ' + json.dumps({'recovered': recovered, 'ed25519_verified': True}))\n"
        )
        done = subprocess.run(
            [py, "manage.py", "shell", "-c", snippet],
            env=backend_env,
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=900,
        )
        marker = [ln for ln in done.stdout.splitlines() if "REHEARSAL_JSON" in ln]
        if done.returncode != 0 or not marker:
            print(done.stdout[-2000:], done.stderr[-2000:])
            return 1
        proof = json.loads(marker[0].split("REHEARSAL_JSON ", 1)[1])
        assert proof["recovered"].lower() == addresses["ethereum"].lower(), proof
        assert proof["ed25519_verified"] is True
        checks["backend_signing"] = {
            "ecdsa_recovered_address": proof["recovered"],
            "ed25519_verified": True,
        }
        print("backend-initiated threshold signatures verified (ECDSA + Ed25519)")

        (RUN_DIR / "rehearsal-record.json").write_text(json.dumps(checks, indent=2))
        print(f"REHEARSAL PASSED — record: {RUN_DIR}/rehearsal-record.json")
        return 0
    finally:
        for proc in processes:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)


RUN_DIR = Path()  # set in main()
if __name__ == "__main__":
    raise SystemExit(main())
