import os
import re
import time
import random
import string
from typing import Optional, Dict, Any, List

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.mail.tm"


def rand_str(n: int = 8) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(n))


def get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def api_get(path: str, token: Optional[str] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path: str, payload: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def list_domains() -> List[str]:
    data = api_get("/domains")
    # data["hydra:member"] has domains objects
    domains = []
    for d in data.get("hydra:member", []):
        dom = d.get("domain")
        if dom:
            domains.append(dom)
    return domains


def create_account(address: str, password: str) -> Dict[str, Any]:
    # If already exists, API returns error. We'll handle that outside.
    return api_post("/accounts", {"address": address, "password": password})


def get_token(address: str, password: str) -> str:
    data = api_post("/token", {"address": address, "password": password})
    token = data.get("token")
    if not token:
        raise RuntimeError("Token not found in response.")
    return token


def fetch_messages(token: str) -> List[Dict[str, Any]]:
    data = api_get("/messages", token=token)
    return data.get("hydra:member", [])


def read_message(token: str, message_id: str) -> Dict[str, Any]:
    return api_get(f"/messages/{message_id}", token=token)


def extract_otp(text: str) -> Optional[str]:
    """
    Tries to find a 4-8 digit OTP/code in text.
    """
    if not text:
        return None
    # Common OTP patterns: 4-8 digits
    m = re.search(r"\b(\d{4,8})\b", text)
    return m.group(1) if m else None


def safe_print_account(address: str, password: str) -> None:
    # Don't print full password in logs
    masked = password[:2] + "*" * max(0, len(password) - 4) + password[-2:] if len(password) >= 4 else "***"
    print(f"✅ Email: {address}")
    print(f"✅ Password: {masked}")


def main():
    load_dotenv()

    # Optional existing credentials
    address = os.getenv("MAILTM_ADDRESS", "").strip()
    password = os.getenv("MAILTM_PASSWORD", "").strip()

    wanted_domain = os.getenv("MAILTM_DOMAIN", "").strip()
    username_prefix = os.getenv("MAILTM_USERNAME_PREFIX", "").strip()

    poll_seconds = get_env_int("POLL_SECONDS", 10)
    max_polls = get_env_int("MAX_POLLS", 30)

    # 1) Domains
    domains = list_domains()
    if not domains:
        raise RuntimeError("No domains returned by API.")

    if wanted_domain:
        if wanted_domain not in domains:
            print("⚠️ MAILTM_DOMAIN not available. Using a random available domain.")
            domain = random.choice(domains)
        else:
            domain = wanted_domain
    else:
        domain = random.choice(domains)

    # 2) If no existing account provided, create a new one
    if not address or not password:
        if not username_prefix:
            username_prefix = "user"

        username = f"{username_prefix}{rand_str(6)}"
        address = f"{username}@{domain}"

        # Make a strong random password
        password = rand_str(10) + "#@" + rand_str(4)

        print("ℹ️ No MAILTM_ADDRESS / MAILTM_PASSWORD provided. Creating a new temp account...")
        try:
            create_account(address, password)
            print("✅ Account created.")
        except requests.HTTPError as e:
            # If account exists or validation error
            print(f"⚠️ Account create failed: {e}")
            print("👉 If you want to use an existing account, set MAILTM_ADDRESS and MAILTM_PASSWORD in env/secrets.")
            # Still continue; maybe it exists and password matches (token step will confirm)

    safe_print_account(address, password)

    # 3) Token
    print("🔐 Getting token...")
    token = get_token(address, password)
    print("✅ Token received.")

    # 4) Poll inbox for messages
    print(f"📩 Polling inbox every {poll_seconds}s (max {max_polls} times)...")

    seen_ids = set()
    for i in range(max_polls):
        msgs = fetch_messages(token)
        # Newest first usually
        if msgs:
            # Filter new messages
            new_msgs = [m for m in msgs if m.get("id") and m.get("id") not in seen_ids]
            for m in new_msgs:
                mid = m.get("id")
                seen_ids.add(mid)

                subject = m.get("subject", "(no subject)")
                from_addr = (m.get("from") or {}).get("address", "(unknown)")
                intro = m.get("intro", "")

                print("\n==============================")
                print(f"🆕 New Message: {mid}")
                print(f"From: {from_addr}")
                print(f"Subject: {subject}")
                print(f"Intro: {intro}")

                # Read full message
                full = read_message(token, mid)
                text = full.get("text", "") or ""
                html = full.get("html", "") or ""

                otp = extract_otp(text) or extract_otp(intro)
                if otp:
                    print(f"✅ OTP/Code found: {otp}")
                else:
                    print("ℹ️ OTP not detected. Showing first 300 chars of body:")
                    print((text[:300] if text else "(no text body)"))

                # If you want, you can save html too (not printing full to keep logs clean)
                if html:
                    print("ℹ️ HTML body exists (not printed).")

            if new_msgs:
                print("==============================\n")

        else:
            print(f"⏳ No messages yet... ({i+1}/{max_polls})")

        time.sleep(poll_seconds)

    print("✅ Done polling.")
    print("Tip: keep this account for further use by saving MAILTM_ADDRESS and MAILTM_PASSWORD as GitHub Secrets.")


if __name__ == "__main__":
    main()

