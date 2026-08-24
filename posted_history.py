"""
Tracks which products have already been posted to avoid repeats.
ASINs expire after 48 hours.
"""
import json
import os
import re
from datetime import datetime, timedelta

EXPIRY_HOURS = 48


class PostedHistory:
    def __init__(self, file_path="posted_history.json"):
        self.file_path = file_path
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"posted": {}, "stats": {"total": 0}}

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[history] Save error: {e}")

    def has_posted(self, asin_or_url):
        key = self._extract_key(asin_or_url)
        if key not in self.data["posted"]:
            return False
        entry = self.data["posted"][key]
        posted_at = entry.get("posted_at") if isinstance(entry, dict) else entry
        try:
            t = datetime.fromisoformat(str(posted_at))
            return datetime.now() - t < timedelta(hours=EXPIRY_HOURS)
        except Exception:
            return False

    def mark_posted(self, asin_or_url, title=None, category=None):
        key = self._extract_key(asin_or_url)
        self.data["posted"][key] = {
            "title": title or "",
            "category": category or "",
            "posted_at": datetime.now().isoformat(),
        }
        self.data["stats"]["total"] = self.data["stats"].get("total", 0) + 1
        self._purge_expired()
        self._save()

    def filter_unposted(self, urls):
        return [u for u in urls if not self.has_posted(u)]

    def total_posted(self):
        return self.data["stats"].get("total", 0)

    def _purge_expired(self):
        now = datetime.now()
        cutoff = timedelta(hours=EXPIRY_HOURS * 2)
        clean = {}
        for key, entry in self.data["posted"].items():
            posted_at = entry.get("posted_at") if isinstance(entry, dict) else entry
            try:
                t = datetime.fromisoformat(str(posted_at))
                if now - t < cutoff:
                    clean[key] = entry
            except Exception:
                pass
        self.data["posted"] = clean

    @staticmethod
    def _extract_key(text):
        m = re.search(r"/dp/([A-Z0-9]{10})", text)
        if m:
            return m.group(1)
        return text
