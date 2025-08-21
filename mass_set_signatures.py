#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import csv
import json
import time
import argparse
import sys
from typing import Dict, List, Any, Optional

import requests
from dotenv import load_dotenv

BASE = "https://api360.yandex.net"

# --------------------------- CLI ---------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Mass update Yandex 360 mail signatures from CSV"
    )
    p.add_argument("--csv", required=True, help="Path to CSV: userId,email,signature[,lang]")
    p.add_argument("--org-id", required=False, default=os.environ.get("ORG_ID"),
                   help="Organization ID (or set ORG_ID env)")
    p.add_argument("--token", required=False, default=os.environ.get("TOKEN"),
                   help="OAuth token with admin rights (or set TOKEN env)")
    p.add_argument("--position", choices=["bottom", "under"], default="bottom",
                   help="Signature position (default: bottom)")
    p.add_argument("--default-lang", default="ru",
                   help="Fallback lang if CSV has none (default: ru)")
    p.add_argument("--merge", action="store_true",
                   help="Merge with existing signatures instead of full replace")
    p.add_argument("--convert-newlines", action="store_true",
                   help="Convert '\\n' in signature to '<br>'")
    p.add_argument("--rps", type=float, default=4.0,
                   help="Requests per second max (default: 4)")
    p.add_argument("--dry-run", action="store_true",
                   help="Do not send changes, just print")
    p.add_argument("--timeout", type=float, default=20.0,
                   help="HTTP timeout seconds")
    p.add_argument("--strict-email", action="store_true",
                   help="Fail the row if CSV email does not belong to the user (otherwise warn and drop 'emails' binding)")
    return p.parse_args()

# ------------------------ HTTP utils -----------------------

def session_with_token(token: str, timeout: float) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"OAuth {token}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    })
    s.request = _wrap_with_timeout(s.request, timeout)
    return s

def _wrap_with_timeout(func, timeout):
    def inner(method, url, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout
        return func(method, url, **kwargs)
    return inner

def backoff_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    retriable = {429, 500, 502, 503, 504}
    last = None
    for attempt in range(1, 7):
        resp = session.request(method, url, **kwargs)
        if resp.status_code in retriable:
            wait = min(30.0, 0.5 * (2 ** (attempt - 1)))
            time.sleep(wait)
            last = resp
            continue
        return resp
    return last if last is not None else resp

# ------------------------ API calls ------------------------

def get_user(session: requests.Session, org_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Получить карточку пользователя:
    /directory/v1/org/{orgId}/users/{userId}
    Возвращает None, если 404.
    """
    url = f"{BASE}/directory/v1/org/{org_id}/users/{user_id}"
    r = backoff_request(session, "GET", url)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def user_owns_email(user: Dict[str, Any], email: str) -> bool:
    """
    Проверяет, что email принадлежит пользователю:
    - основной email (user['email'])
    - алиасы (user['aliases'] или user['emails'] если присутствуют)
    Сравнение регистронезависимое.
    """
    if not email:
        return False
    needle = email.strip().lower()

    # основной
    primary = (user.get("email") or "").strip().lower()
    if primary and primary == needle:
        return True

    # возможные коллекции алиасов в разных инсталляциях
    for key in ("aliases", "emails", "alternateEmails"):
        maybe = user.get(key)
        if isinstance(maybe, list):
            for e in maybe:
                if isinstance(e, str) and e.strip().lower() == needle:
                    return True
                if isinstance(e, dict):
                    # иногда элементы бывают словарями: {"address":"...","type":"alias"}
                    addr = (e.get("address") or "").strip().lower()
                    if addr == needle:
                        return True

    return False

def get_sender_info(session: requests.Session, org_id: str, user_id: str) -> Dict[str, Any]:
    url = f"{BASE}/admin/v1/org/{org_id}/mail/users/{user_id}/settings/sender_info"
    r = backoff_request(session, "GET", url)
    if r.status_code == 404:
        return {"signs": [], "signPosition": "bottom"}
    r.raise_for_status()
    return r.json()

def post_sender_info(session: requests.Session, org_id: str, user_id: str, body: Dict[str, Any]) -> requests.Response:
    url = f"{BASE}/admin/v1/org/{org_id}/mail/users/{user_id}/settings/sender_info"
    return backoff_request(session, "POST", url, data=json.dumps(body, ensure_ascii=False))

# --------------------- business logic ----------------------

def normalize_signature(text: str, convert_newlines: bool) -> str:
    if convert_newlines:
        return text.replace("\\n", "<br>").replace("\n", "<br>")
    return text

def upsert_sign(signs: List[Dict[str, Any]], lang: str, email: str, text: str, make_default=True) -> List[Dict[str, Any]]:
    # снять default у остальных с тем же lang
    if make_default:
        for s in signs:
            if s.get("lang") == lang:
                s["isDefault"] = False

    # найти существующую подпись с тем же lang и той же привязкой emails
    target_idx = None
    for i, s in enumerate(signs):
        if s.get("lang") != lang:
            continue
        cur_emails = sorted(s.get("emails", []))
        want_emails = sorted([email]) if email else []
        if cur_emails == want_emails:
            target_idx = i
            break

    new_entry = {"text": text, "lang": lang, "isDefault": bool(make_default)}
    if email:
        new_entry["emails"] = [email]

    if target_idx is None:
        signs.append(new_entry)
    else:
        signs[target_idx].update(new_entry)

    return signs

# --------------------------- main --------------------------

def main():
    load_dotenv()  # загрузить .env

    args = parse_args()

    if not args.org_id:
        sys.exit("Укажите --org-id или переменную окружения ORG_ID (в .env)")
    if not args.token:
        sys.exit("Укажите --token или переменную окружения TOKEN (в .env)")

    sess = session_with_token(args.token, args.timeout)
    interval = 1.0 / max(args.rps, 0.1)

    # читаем CSV
    with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            sys.exit("CSV пустой или без заголовка. Нужны колонки: userId,email,signature[,lang]")
        headers = [h.strip() for h in reader.fieldnames]
        missing = {"userId", "email", "signature"} - set(headers)
        if missing:
            sys.exit(f"В CSV не хватает колонок: {', '.join(missing)}")

        rows = []
        for raw in reader:
            row = {k.strip(): (v if v is not None else "") for k, v in raw.items()}
            rows.append(row)

    for idx, row in enumerate(rows, start=1):
        user_id = (row.get("userId") or "").strip()
        csv_email = (row.get("email") or "").strip()
        text = (row.get("signature") or "").strip()
        lang = (row.get("lang") or args.default_lang).strip().lower() or args.default_lang

        if not user_id or not text:
            print(f"[SKIP] row={idx}: missing userId or signature")
            continue

        # Проверка владельца email (если указан)
        email_to_bind: Optional[str] = None
        if csv_email:
            user = get_user(sess, args.org_id, user_id)
            if user is None:
                msg = f"[FAIL] userId={user_id}: user not found (404)"
                if args.strict_email:
                    print(msg)
                    time.sleep(interval)
                    continue
                else:
                    print(msg + " — drop email binding, proceed without 'emails'")
            else:
                if user_owns_email(user, csv_email):
                    email_to_bind = csv_email
                else:
                    msg = f"[{'FAIL' if args.strict_email else 'WARN'}] userId={user_id}: email '{csv_email}' does not belong to user"
                    if args.strict_email:
                        print(msg)
                        time.sleep(interval)
                        continue
                    else:
                        print(msg + " — drop email binding, proceed without 'emails'")

        text_norm = normalize_signature(text, args.convert_newlines)

        if args.merge:
            # GET текущие и апдейт
            try:
                current = get_sender_info(sess, args.org_id, user_id)
            except requests.HTTPError as e:
                print(f"[FAIL][{user_id}] GET sender_info: {e}")
                time.sleep(interval)
                continue

            signs = current.get("signs", [])
            signs = upsert_sign(signs, lang=lang, email=email_to_bind, text=text_norm, make_default=True)
            body = {"signs": signs, "signPosition": current.get("signPosition") or args.position}
        else:
            # Полная замена — одна дефолтная подпись
            one = {"text": text_norm, "lang": lang, "isDefault": True}
            if email_to_bind:
                one["emails"] = [email_to_bind]
            body = {"signs": [one], "signPosition": args.position}

        if args.dry_run:
            print(f"[DRY] userId={user_id} body={json.dumps(body, ensure_ascii=False)}")
        else:
            resp = post_sender_info(sess, args.org_id, user_id, body)
            if resp.status_code == 200:
                print(f"[OK ] userId={user_id}")
            else:
                print(f"[FAIL] userId={user_id} status={resp.status_code} body={resp.text}")

        time.sleep(interval)

if __name__ == "__main__":
    main()
