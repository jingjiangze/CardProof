# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import hashlib
import importlib.machinery
import importlib.util
import html as html_lib
import json
import marshal
import mimetypes
import os
import re
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import winreg


def _impl_candidates() -> list[Path]:
    app_dir = Path(sys.argv[0]).resolve().parent
    meipass = Path(getattr(sys, '_MEIPASS', ''))
    return [
        app_dir / 'desktop_app_impl.pyc',
        meipass / 'desktop_app_impl.pyc',
        app_dir / '__pycache__' / 'desktop_app.cpython-312.pyc',
        app_dir / 'desktop_app.pyc',
        meipass / '__pycache__' / 'desktop_app.cpython-312.pyc',
        meipass / 'desktop_app.pyc',
    ]


def _load_impl():
    for candidate in _impl_candidates():
        if not candidate or not candidate.exists():
            continue
        try:
            code = marshal.loads(candidate.read_bytes())
        except Exception:
            continue
        module = types.ModuleType('desktop_app_impl')
        module.__file__ = str(candidate)
        module.__package__ = ''
        sys.modules['desktop_app_impl'] = module
        exec(code, module.__dict__)
        return module
    raise FileNotFoundError('unable to locate desktop_app_impl.pyc')


def _show_bootstrap_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, 'CardProof', 0x10)
    except Exception:
        try:
            sys.stderr.write(message + '\n')
        except Exception:
            pass


try:
    mod = _load_impl()
except ModuleNotFoundError as exc:
    _show_bootstrap_error(
        'Startup failed. Missing required component: '
        f'{exc}.\nPlease run the latest build, or reinstall the full Windows Python components and try again.'
    )
    raise SystemExit(1) from None


tk = mod.tk
ttk = mod.ttk


def _runtime_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _runtime_app_dir()
mod.APP_DIR = APP_DIR
CONFIG_PATH = APP_DIR / "app_config.json"
mod.CONFIG_PATH = CONFIG_PATH
CONFIG_REG_PATH = r"Software\CardProof"
DEFAULT_CONFIG = dict(mod.DEFAULT_CONFIG)
DEFAULT_CONFIG.setdefault("order_range_mode", "today")
DEFAULT_CONFIG.setdefault("order_range_days", 2)
DEFAULT_CONFIG.setdefault("order_range_start_date", "")
DEFAULT_CONFIG.setdefault("order_range_start_time", "00:00")
DEFAULT_CONFIG.setdefault("openai_provider", "builtin")
DEFAULT_CONFIG.setdefault("openai_base_url", "https://api.openai.com/v1")
DEFAULT_CONFIG.setdefault("openai_api_key", "")
DEFAULT_CONFIG.setdefault("openai_custom_base_url", "")
DEFAULT_CONFIG.setdefault("cache_dir", "")
DEFAULT_CONFIG.setdefault("old_watch_enabled", True)
DEFAULT_CONFIG.setdefault("old_seed_days", 1)
DEFAULT_CONFIG.setdefault("old_prune_days", 30)
DEFAULT_CONFIG.setdefault("launch_at_startup", False)
mod.DEFAULT_CONFIG = DEFAULT_CONFIG

API_PROVIDER_LABELS = {
    "builtin": "\u5185\u7f6e",
    "doubao": "\u706b\u5c71\u8c46\u5305",
    "custom": "\u81ea\u5b9a\u4e49",
}

API_PROVIDER_URLS = {
    "builtin": "https://api.openai.com/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
}

API_PROVIDER_DEFAULT_MODELS = {
    "builtin": "gpt-4.1-mini",
    "doubao": "doubao-seed-2-0-mini-260428",
    "custom": "",
}


def _default_local_cache_dir(root: str | Path | None) -> str:
    raw = str(root or "").strip()
    if not raw:
        return str(APP_DIR / "cache")
    try:
        return str(Path(raw).expanduser().resolve() / "cache")
    except Exception:
        return str(Path(raw) / "cache")


def _normalize_api_provider(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"builtin", "doubao", "custom"}:
        return raw
    if raw in {"\u5185\u7f6e", "\u9ed8\u8ba4", "auto"}:
        return "builtin"
    if raw in {"\u706b\u5c71\u8c46\u5305", "ark"}:
        return "doubao"
    if raw == "\u81ea\u5b9a\u4e49":
        return "custom"
    return "builtin"


def _resolve_api_base_url(provider: str | None, custom_base_url: str | None = None) -> str:
    kind = _normalize_api_provider(provider)
    if kind == "custom":
        custom = str(custom_base_url or "").strip()
        return custom or API_PROVIDER_URLS["builtin"]
    return API_PROVIDER_URLS.get(kind, API_PROVIDER_URLS["builtin"])


def _resolve_default_model(provider: str | None) -> str:
    return API_PROVIDER_DEFAULT_MODELS.get(_normalize_api_provider(provider), "")


def _build_api_headers(api_key: str, auth_style: str | None) -> dict[str, str]:
    key = str(api_key or "").strip()
    style = str(auth_style or "dual").strip().lower()
    headers = {
        "Accept": "application/json",
        "User-Agent": "CardProof/1.0",
    }
    if not key:
        return headers
    if style in {"dual", "bearer"}:
        headers["Authorization"] = f"Bearer {key}"
    if style in {"dual", "api-key"}:
        headers["api-key"] = key
        headers["x-api-key"] = key
    return headers


def _candidate_model_urls(base_url: str) -> list[str]:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        return []
    urls = [f"{raw}/models"]
    parsed = urllib.parse.urlparse(raw)
    path = parsed.path.rstrip("/")
    if path and not path.endswith("/v1") and not path.endswith("/api/v3"):
        prefix = raw.rstrip("/")
        urls.append(f"{prefix}/v1/models")
    deduped = []
    seen = set()
    for item in urls:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _extract_model_ids(payload) -> list[str]:
    items = []
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            items = payload.get("data") or []
        elif isinstance(payload.get("models"), list):
            items = payload.get("models") or []
        elif isinstance(payload.get("result"), dict):
            result = payload.get("result") or {}
            if isinstance(result.get("data"), list):
                items = result.get("data") or []
            elif isinstance(result.get("models"), list):
                items = result.get("models") or []
    elif isinstance(payload, list):
        items = payload

    model_ids = []
    seen = set()
    for item in items:
        model_id = None
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
        model_id = str(model_id or "").strip()
        if model_id and model_id not in seen:
            seen.add(model_id)
            model_ids.append(model_id)
    return model_ids


def _fetch_remote_models(base_url: str, api_key: str, auth_style: str | None, timeout: int = 15) -> list[str]:
    errors = []
    for url in _candidate_model_urls(base_url):
        request = urllib.request.Request(url, headers=_build_api_headers(api_key, auth_style), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                payload = json.loads(response.read().decode(charset, errors="replace"))
                models = _extract_model_ids(payload)
                if models:
                    return models
                errors.append(f"{url}: empty model list")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            detail = body or exc.reason or str(exc)
            errors.append(f"{url}: {exc.code} {detail}")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    joined = " | ".join(errors) if errors else "unknown error"
    raise RuntimeError(joined)


def _normalize_loaded_config(config: dict) -> dict:
    data = dict(config or {})
    provider = _normalize_api_provider(data.get("openai_provider"))
    data["openai_provider"] = provider
    data["openai_custom_base_url"] = str(data.get("openai_custom_base_url", "") or "").strip()
    data["openai_base_url"] = _resolve_api_base_url(provider, data["openai_custom_base_url"] or data.get("openai_base_url"))
    data["openai_api_key"] = str(data.get("openai_api_key", "") or "").strip()
    data["order_range_mode"] = _normalize_order_range_mode(data.get("order_range_mode"))
    try:
        data["order_range_days"] = max(0, int(data.get("order_range_days", DEFAULT_CONFIG.get("order_range_days", 2)) or 0))
    except Exception:
        data["order_range_days"] = int(DEFAULT_CONFIG.get("order_range_days", 2))
    data["order_range_start_date"] = str(data.get("order_range_start_date", "") or "").strip()
    data["order_range_start_time"] = str(data.get("order_range_start_time", "00:00") or "00:00").strip() or "00:00"
    data["old_watch_enabled"] = bool(data.get("old_watch_enabled", DEFAULT_CONFIG.get("old_watch_enabled", True)))
    try:
        data["old_seed_days"] = max(0, int(data.get("old_seed_days", DEFAULT_CONFIG.get("old_seed_days", 1)) or 0))
    except Exception:
        data["old_seed_days"] = int(DEFAULT_CONFIG.get("old_seed_days", 1))
    try:
        data["old_prune_days"] = max(0, int(data.get("old_prune_days", DEFAULT_CONFIG.get("old_prune_days", 30)) or 0))
    except Exception:
        data["old_prune_days"] = int(DEFAULT_CONFIG.get("old_prune_days", 30))
    data["launch_at_startup"] = bool(data.get("launch_at_startup", DEFAULT_CONFIG.get("launch_at_startup", False)))
    data["auto_sync_old_files"] = False
    data.pop("sync_target_root", None)
    data.pop("sync_interval_minutes", None)
    if str(data.get("source_mode", "local") or "local").strip().lower() == "local":
        local_root = str(data.get("local_root", "") or "").strip()
        default_cache = _default_local_cache_dir(local_root)
        current_cache = str(data.get("cache_dir", "") or "").strip()
        if not current_cache or current_cache.startswith(str(APP_DIR / "cache")):
            data["cache_dir"] = default_cache
    data["cache_dir"] = str(data.get("cache_dir", "") or "").strip()
    return data


def _read_runtime_config() -> dict:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CONFIG_REG_PATH, 0, winreg.KEY_READ) as key:
            raw, _ = winreg.QueryValueEx(key, "ConfigJson")
        if not raw:
            return {}
        return json.loads(str(raw))
    except Exception:
        return {}


def _write_runtime_config(config: dict) -> None:
    payload = json.dumps(config, ensure_ascii=False)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CONFIG_REG_PATH) as key:
        winreg.SetValueEx(key, "ConfigJson", 0, winreg.REG_SZ, payload)


def _ensure_runtime_config_file(seed: dict | None = None) -> dict:
    current = _normalize_loaded_config(dict(seed or _read_runtime_config() or {}))
    if not _read_runtime_config():
        _write_runtime_config(current)
    return current


def _load_config_with_defaults():
    config = _read_runtime_config()
    merged = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        merged.update(config)
    return _normalize_loaded_config(merged)


mod.load_config = _load_config_with_defaults
mod.save_config = _write_runtime_config

FACE_FRONT = "\u6b63\u9762"
FACE_BACK = "\u53cd\u9762"


def _public_old_name(name: str) -> str:
    path = Path(name or "")
    return f"{path.stem}old{path.suffix or '.jpg'}"


def _normalize_compare_stem(name: str) -> str:
    stem = Path(name or "").stem.lower()
    stem = re.sub(r"(old|\u753b\u677f|\u756b\u677f)", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[\W_]+", "", stem)
    return stem


def _pair_info_from_name(name: str) -> tuple[str, str | None]:
    stem = Path(name or "").stem
    normalized = re.sub(r"(old|\u753b\u677f|\u756b\u677f)", "", stem, flags=re.IGNORECASE)
    digits = re.findall(r"(\d+)", normalized)
    face_label = None
    pair_key_raw = normalized
    if digits:
        number_text = digits[-1]
        try:
            face_label = FACE_FRONT if int(number_text) % 2 == 1 else FACE_BACK
        except Exception:
            face_label = None
        pair_key_raw = re.sub(r"(\d+)(?!.*\d)", "", normalized)
    pair_key = re.sub(r"[\W_]+", "", pair_key_raw).lower() or _normalize_compare_stem(name)
    return pair_key, face_label


def _old_rel_path(rel_path: str) -> str:
    path = Path(rel_path or "")
    filename = _public_old_name(path.name)
    if str(path.parent) in ("", "."):
        return filename
    return str(path.parent / filename).replace("\\", "/")


ORDER_RANGE_LABELS = {
    "today": "\u4eca\u5929",
    "days": "\u8fd1N\u5929",
    "since": "\u81ea\u5b9a\u4e49\u8d77\u59cb",
    "all": "\u5168\u90e8",
}


def _normalize_order_range_mode(value: str | None) -> str:
    raw = str(value or "today").strip()
    reverse = {v: k for k, v in ORDER_RANGE_LABELS.items()}
    return reverse.get(raw, raw if raw in ORDER_RANGE_LABELS else "today")

_orig_build_left = mod.ProofApp._build_left
_orig_refresh_orders = mod.ProofApp.refresh_orders
_orig_build_prompt = mod.OpenAIClient.build_prompt


def _ensure_range_vars(self):
    if not hasattr(self, "order_range_mode_var"):
        default_mode = DEFAULT_CONFIG.get("order_range_mode", "today")
        current_mode = self.config_data.get("order_range_mode", default_mode)
        self.order_range_mode_var = tk.StringVar(value=ORDER_RANGE_LABELS.get(_normalize_order_range_mode(current_mode), "\u4eca\u5929"))
    if not hasattr(self, "order_range_days_var"):
        self.order_range_days_var = tk.IntVar(value=int(self.config_data.get("order_range_days", DEFAULT_CONFIG.get("order_range_days", 2))))
    if not hasattr(self, "order_range_start_date_var"):
        self.order_range_start_date_var = tk.StringVar(value=str(self.config_data.get("order_range_start_date", DEFAULT_CONFIG.get("order_range_start_date", ""))))
    if not hasattr(self, "order_range_start_time_var"):
        self.order_range_start_time_var = tk.StringVar(value=str(self.config_data.get("order_range_start_time", DEFAULT_CONFIG.get("order_range_start_time", "00:00"))))
    if not hasattr(self, "proofread_face_mode_var"):
        self.proofread_face_mode_var = tk.StringVar(value="front")


def _resolve_order_cutoff(self):
    _ensure_range_vars(self)
    mode = _normalize_order_range_mode(self.order_range_mode_var.get())
    now = datetime.now().astimezone()
    if mode == "all":
        return None
    if mode == "days":
        try:
            days = max(0, int(self.order_range_days_var.get()))
        except Exception:
            days = 1
        return now - timedelta(days=days)
    if mode == "since":
        date_text = str(self.order_range_start_date_var.get()).strip()
        time_text = str(self.order_range_start_time_var.get()).strip() or "00:00"
        try:
            if not date_text:
                return now.replace(hour=0, minute=0, second=0, microsecond=0)
            stamp = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
            return stamp.replace(tzinfo=now.tzinfo)
        except Exception:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _build_left(self):
    _orig_build_left(self)
    _ensure_range_vars(self)

    try:
        for child in self.left.winfo_children():
            info = child.grid_info()
            row = int(info.get("row", 0) or 0)
            if row >= 3:
                child.grid_configure(row=row + 1)
        self.left.rowconfigure(4, weight=0)
        self.left.rowconfigure(5, weight=1)
    except Exception:
        pass

    range_row = ttk.Frame(self.left)
    range_row.grid(row=3, column=0, sticky="ew", pady=(0, 10))
    for col in range(8):
        range_row.columnconfigure(col, weight=1 if col in (1, 3, 5, 7) else 0)

    ttk.Label(range_row, text="范围", style="Status.TLabel").grid(row=0, column=0, sticky="w")
    mode = ttk.Combobox(
        range_row,
        textvariable=self.order_range_mode_var,
        values=tuple(ORDER_RANGE_LABELS.values()),
        width=8,
        state="readonly",
    )
    mode.grid(row=0, column=1, sticky="ew", padx=(6, 8))

    ttk.Label(range_row, text="天数", style="Status.TLabel").grid(row=0, column=2, sticky="w")
    days = ttk.Spinbox(range_row, from_=0, to=3650, textvariable=self.order_range_days_var, width=6)
    days.grid(row=0, column=3, sticky="ew", padx=(6, 8))

    ttk.Label(range_row, text="起始", style="Status.TLabel").grid(row=0, column=4, sticky="w")
    start_date = ttk.Entry(range_row, textvariable=self.order_range_start_date_var, width=11)
    start_date.grid(row=0, column=5, sticky="ew", padx=(6, 8))
    start_time = ttk.Entry(range_row, textvariable=self.order_range_start_time_var, width=7)
    start_time.grid(row=0, column=6, sticky="ew", padx=(0, 8))
    ttk.Button(range_row, text="刷新范围", command=self.refresh_orders).grid(row=0, column=7, sticky="e")

    mode.bind("<<ComboboxSelected>>", lambda _e: self.refresh_orders())
    days.bind("<Return>", lambda _e: self.refresh_orders())
    start_date.bind("<Return>", lambda _e: self.refresh_orders())
    start_time.bind("<Return>", lambda _e: self.refresh_orders())


def _refresh_orders(self):
    self.set_status("正在刷新目录...")
    self._source_refresh_nonce += 1
    cutoff = _resolve_order_cutoff(self)
    self._run_bg(
        lambda: self.source.list_orders(prefer_cache=False, cutoff=cutoff),
        self.on_orders_loaded,
        self.on_error,
    )


def _version_paths(self, item):
    order_root, relative = self._local_backup_roots(item)
    return order_root / "old" / ".versions" / relative, order_root / "old" / relative


def _record_version_backup(self, item, data: bytes) -> None:
    if not item.local_path or not item.rel_path:
        return
    try:
        snapshot_file, old_file = _version_paths(self, item)
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.parent.mkdir(parents=True, exist_ok=True)
        modified_at = item.modified_at or datetime.now().astimezone()
        current_hash = hashlib.sha256(data).hexdigest()
        previous = None
        if snapshot_file.exists():
            try:
                previous = mod.read_bytes_stable(snapshot_file)
            except Exception:
                previous = None
        if previous is None:
            mod.atomic_write_bytes(snapshot_file, data)
            try:
                os.utime(snapshot_file, (modified_at.timestamp(), modified_at.timestamp()))
            except Exception:
                pass
            return
        if previous != data:
            mod.atomic_write_bytes(old_file, previous)
            try:
                os.utime(old_file, (modified_at.timestamp(), modified_at.timestamp()))
            except Exception:
                pass
            mod.atomic_write_bytes(snapshot_file, data)
            try:
                os.utime(snapshot_file, (modified_at.timestamp(), modified_at.timestamp()))
            except Exception:
                pass
    except Exception:
        pass


def _load_version_backup(self, item):
    if not item.local_path or not item.rel_path:
        return None
    try:
        _, old_file = _version_paths(self, item)
        if not old_file.exists():
            return None
        data = mod.read_bytes_stable(old_file)
        modified_at = datetime.fromtimestamp(old_file.stat().st_mtime).astimezone()
        return mod.FileItem(
            name=item.name,
            rel_path=item.rel_path,
            modified_at=modified_at,
            size=len(data),
            source=item.source,
            local_path=str(old_file),
            mime_type=item.mime_type,
            data=data,
            physical_size_mm=mod.detect_physical_size_mm(data=data),
            version_label="旧版",
            face_label=item.face_label,
            pair_key=item.pair_key,
        )
    except Exception:
        return None


def _build_prompt(self, source_text: str, notes: str, files: list, root_hint: str) -> str:
    file_lines = "\n".join(
        f"{idx + 1}. [{item.version_label or '最新版'} / {item.face_label or '未标记'}] {item.rel_path}  {mod.fmt_dt(item.modified_at)}"
        + (f"  {item.physical_size_mm} mm" if item.physical_size_mm else "")
        for idx, item in enumerate(files)
    )
    template = self.proofread_prompt or mod.DEFAULT_PROOFREAD_PROMPT
    return (
        template.replace("[[ROOT_HINT]]", root_hint or "[未提供]")
        .replace("[[SOURCE_TEXT]]", source_text or "[未提供]")
        .replace("[[NOTES]]", notes or "[无]")
        .replace("[[CUSTOM_PROMPT]]", self.custom_prompt or "[无]")
        .replace("[[FILE_LINES]]", file_lines or "[无]")
    )


def _patch_source_client(cls):
    if cls.__name__ == "WebDavClient":
        def list_today_files(self, cutoff=None):
            found = []

            def walk(rel_dir: str = "") -> None:
                for item in self.propfind(rel_dir, depth=1):
                    rel_path = self.relative_path_from_href(item["href_path"])
                    if not rel_path:
                        continue
                    if item["is_collection"]:
                        walk(rel_path)
                        continue
                    if not rel_path.lower().endswith((".jpg", ".jpeg")):
                        continue
                    modified_at = item["modified_at"]
                    if not modified_at or (cutoff is not None and modified_at < cutoff):
                        continue
                    found.append(
                        mod.FileItem(
                            name=item["name"],
                            rel_path=rel_path,
                            modified_at=modified_at,
                            size=item["size"],
                            source="dav",
                        )
                    )

            walk("")
            found.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return found

        def list_orders(self, refresh_budget=None, prefer_cache=False, cutoff=None):
            groups: dict[str, list] = {}
            for file_item in list_today_files(self, cutoff=cutoff):
                order_id = mod.rel_top_folder(file_item.rel_path)
                groups.setdefault(order_id, []).append(file_item)

            orders = []
            for order_id, files in groups.items():
                latest = max((f.modified_at for f in files if f.modified_at), default=None)
                files.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                orders.append(mod.OrderItem(order_id=order_id, files=files, latest_modified_at=latest))

            orders.sort(key=lambda x: x.latest_modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return orders

        cls.list_today_files = list_today_files
        cls.list_orders = list_orders
        return

    if cls.__name__ == "OpenListBrowserClient":
        def _collect_today_images(self, rel_dir, cutoff=None):
            results = []
            for item in self.list_directory(rel_dir):
                if item.is_dir:
                    results.extend(_collect_today_images(self, item.rel_path, cutoff))
                    continue
                if not item.name.lower().endswith((".jpg", ".jpeg")):
                    continue
                if not item.modified_at or (cutoff is not None and item.modified_at < cutoff):
                    continue
                results.append(item)
            return results

        def list_today_files(self, cutoff=None):
            orders = list_orders(self, cutoff=cutoff)
            found = [item for order in orders for item in order.files]
            found.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return found

        def list_orders(self, refresh_budget=None, prefer_cache=False, cutoff=None):
            orders = []
            root_items = self.list_directory("")
            folders = [item for item in root_items if item.is_dir]
            root_files = [
                item
                for item in root_items
                if not item.is_dir and item.name.lower().endswith((".jpg", ".jpeg"))
                and item.modified_at and (cutoff is None or item.modified_at >= cutoff)
            ]

            def scan_folder(folder):
                return folder, _collect_today_images(self, folder.rel_path, cutoff)

            if folders:
                worker_count = min(8, len(folders)) or 1
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    scanned = list(pool.map(scan_folder, folders))
            else:
                scanned = []

            for folder, files in scanned:
                if not files:
                    continue
                files.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                latest = max((f.modified_at for f in files if f.modified_at), default=folder.modified_at)
                orders.append(mod.OrderItem(order_id=folder.name, files=files, latest_modified_at=latest))

            if root_files:
                root_files.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                latest = max((f.modified_at for f in root_files if f.modified_at), default=None)
                orders.append(mod.OrderItem(order_id="root", files=root_files, latest_modified_at=latest))

            orders.sort(key=lambda x: x.latest_modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return orders

        cls._collect_today_images = _collect_today_images
        cls.list_today_files = list_today_files
        cls.list_orders = list_orders
        return

    if cls.__name__ == "LocalFolderClient":
        _orig_local_init = getattr(cls, "__init__", None)

        def __init__(self, *args, **kwargs):
            if _orig_local_init is not None:
                _orig_local_init(self, *args, **kwargs)
            if not hasattr(self, "bytes_cache") or self.bytes_cache is None:
                self.bytes_cache = {}

        def download(self, rel_path, *args, **kwargs):
            if not hasattr(self, "bytes_cache") or self.bytes_cache is None:
                self.bytes_cache = {}
            path = Path(rel_path or "")
            if not path.is_absolute():
                path = Path(self.root_dir) / path
            path = path.expanduser().resolve()
            try:
                stat = path.stat()
            except Exception:
                raise
            key = str(path)
            cached = self.bytes_cache.get(key)
            if isinstance(cached, tuple) and len(cached) == 3:
                cached_mtime_ns, cached_size, cached_data = cached
                if cached_mtime_ns == stat.st_mtime_ns and cached_size == stat.st_size:
                    return cached_data
            reader = getattr(mod, "read_bytes_stable", None)
            data = reader(path) if callable(reader) else path.read_bytes()
            self.bytes_cache[key] = (stat.st_mtime_ns, stat.st_size, data)
            return data

        cls.__init__ = __init__
        cls.download = download

        def _list_top_entries(self, cutoff=None):
            top_dirs = []
            root_files = []
            try:
                with os.scandir(self.root_dir) as it:
                    for entry in it:
                        try:
                            if entry.name in {"old", ".cardproof"} or entry.name.startswith(".cardproof"):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stat = entry.stat(follow_symlinks=False)
                                top_dirs.append((Path(entry.path), datetime.fromtimestamp(stat.st_mtime).astimezone()))
                            elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith((".jpg", ".jpeg")):
                                stat = entry.stat(follow_symlinks=False)
                                modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
                                if cutoff is None or modified_at >= cutoff:
                                    root_files.append(
                                        mod.FileItem(
                                            name=entry.name,
                                            rel_path=self._rel_path(Path(entry.path)),
                                            modified_at=modified_at,
                                            size=stat.st_size,
                                            source="local",
                                            local_path=str(Path(entry.path)),
                                            mime_type=mimetypes.guess_type(entry.name)[0] or "image/jpeg",
                                        )
                                    )
                        except Exception:
                            continue
            except Exception:
                pass
            top_dirs.sort(key=lambda x: x[1], reverse=True)
            root_files.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return top_dirs, root_files

        def _scan_order_dir(self, order_dir, cutoff=None, file_budget=None):
            results = []
            latest_modified_at = None
            stack = [order_dir]

            def entry_mtime(entry) -> float:
                try:
                    return entry.stat(follow_symlinks=False).st_mtime
                except Exception:
                    return 0.0

            while stack:
                current = stack.pop()
                try:
                    with os.scandir(current) as it:
                        entries = list(it)
                        entries.sort(key=lambda entry: (0 if entry.is_file(follow_symlinks=False) else 1, -entry_mtime(entry)))
                        for entry in entries:
                            try:
                                if entry.name in {"old", ".cardproof"} or entry.name.startswith(".cardproof"):
                                    continue
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append(Path(entry.path))
                                    continue
                                lower_name = entry.name.lower()
                                stat = entry.stat(follow_symlinks=False)
                                image_mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()
                                if lower_name.endswith(".ai"):
                                    if cutoff is None or image_mtime >= cutoff:
                                        if latest_modified_at is None or image_mtime > latest_modified_at:
                                            latest_modified_at = image_mtime
                                    continue
                                if not lower_name.endswith((".jpg", ".jpeg")):
                                    continue
                                paired_ai_mtime = self._paired_ai_mtime(Path(entry.path))
                                modified_at = paired_ai_mtime or image_mtime
                                if cutoff is not None and modified_at < cutoff:
                                    continue
                                if latest_modified_at is None or modified_at > latest_modified_at:
                                    latest_modified_at = modified_at
                                results.append(
                                    mod.FileItem(
                                        name=entry.name,
                                        rel_path=self._rel_path(Path(entry.path)),
                                        modified_at=modified_at,
                                        size=stat.st_size,
                                        source="local",
                                        local_path=str(Path(entry.path)),
                                        mime_type=mimetypes.guess_type(entry.name)[0] or "image/jpeg",
                                    )
                                )
                                if file_budget is not None and len(results) >= file_budget:
                                    return results, latest_modified_at
                            except Exception:
                                continue
                except Exception:
                    continue
            return results, latest_modified_at

        def list_today_files(self, cutoff=None):
            found = []
            scanned, _latest = _scan_order_dir(self, self.root_dir, cutoff)
            found.extend(scanned)
            found.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return found

        def list_orders(self, refresh_budget=None, prefer_cache=False, cutoff=None):
            top_dirs, root_files = _list_top_entries(self, cutoff)
            orders = []
            if top_dirs:
                worker_count = min(8, len(top_dirs)) or 1
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    scanned = list(pool.map(lambda pair: _scan_order_dir(self, pair[0], cutoff), top_dirs))
                for (order_dir, _mtime), (files, latest_scan) in zip(top_dirs, scanned):
                    if not files:
                        continue
                    latest = latest_scan or max((f.modified_at for f in files if f.modified_at), default=None)
                    files.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                    orders.append(mod.OrderItem(order_id=order_dir.name, files=files, latest_modified_at=latest))

            if root_files:
                latest = max((f.modified_at for f in root_files if f.modified_at), default=None)
                orders.append(mod.OrderItem(order_id="root", files=root_files, latest_modified_at=latest))

            orders.sort(key=lambda x: x.latest_modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return orders

        cls._list_top_entries = _list_top_entries
        cls._scan_order_dir = _scan_order_dir
        cls.list_today_files = list_today_files
        cls.list_orders = list_orders
        return


_orig_open_settings = mod.ProofApp.open_settings


def _iter_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _iter_widgets(child)


def _safe_text(widget) -> str:
    try:
        return str(widget.cget("text"))
    except Exception:
        return ""


def _find_settings_dialog(app):
    dialogs = [child for child in app.winfo_children() if child.winfo_class() == "Toplevel"]
    return dialogs[-1] if dialogs else None


def _find_settings_inner_frame(dialog):
    for widget in _iter_widgets(dialog):
        if widget.winfo_class() == "Canvas":
            children = widget.winfo_children()
            if children:
                return children[0], widget
    return None, None


def _patched_open_settings(self):
    _ensure_range_vars(self)
    existing = set(self.winfo_children())
    _orig_open_settings(self)
    self.update_idletasks()
    dialog = None
    for child in self.winfo_children():
        if child.winfo_class() == "Toplevel" and child not in existing:
            dialog = child
    dialog = dialog or _find_settings_dialog(self)
    if dialog is None or getattr(dialog, "_cardproof_range_patched", False):
        return
    inner, canvas = _find_settings_inner_frame(dialog)
    if inner is None:
        return

    target_row = None
    for child in inner.winfo_children():
        info = child.grid_info()
        if not info:
            continue
        for sub in child.winfo_children():
            if _safe_text(sub) == "核稿提示词模板":
                target_row = int(info.get("row", 0))
                break
        if target_row is not None:
            break
    if target_row is None:
        target_row = max((int(child.grid_info().get("row", 0)) for child in inner.winfo_children() if child.grid_info()), default=0)

    for child in inner.winfo_children():
        info = child.grid_info()
        if info and int(info.get("row", 0)) >= target_row:
            child.grid_configure(row=int(info.get("row", 0)) + 2)

    range_row = ttk.Frame(inner, style="Panel.TFrame")
    range_row.grid(row=target_row, column=0, sticky="ew", padx=14, pady=(8, 0))
    range_row.columnconfigure(1, weight=1)
    ttk.Label(range_row, text="查看范围").grid(row=0, column=0, sticky="w")
    ttk.Combobox(
        range_row,
        textvariable=self.order_range_mode_var,
        values=("今天", "近N天", "自定义起始", "全部"),
        state="readonly",
    ).grid(row=0, column=1, sticky="ew", padx=(12, 0))

    range_row2 = ttk.Frame(inner, style="Panel.TFrame")
    range_row2.grid(row=target_row + 1, column=0, sticky="ew", padx=14, pady=(8, 0))
    range_row2.columnconfigure(1, weight=1)
    range_row2.columnconfigure(3, weight=1)
    range_row2.columnconfigure(4, weight=1)
    ttk.Label(range_row2, text="近N天").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(range_row2, from_=0, to=3650, textvariable=self.order_range_days_var, width=8).grid(row=0, column=1, sticky="ew", padx=(12, 12))
    ttk.Label(range_row2, text="起始时间").grid(row=0, column=2, sticky="w")
    ttk.Entry(range_row2, textvariable=self.order_range_start_date_var, width=12).grid(row=0, column=3, sticky="ew", padx=(12, 8))
    ttk.Entry(range_row2, textvariable=self.order_range_start_time_var, width=8).grid(row=0, column=4, sticky="ew")

    save_button = None
    for widget in _iter_widgets(dialog):
        if widget.winfo_class() == "TButton" and _safe_text(widget) == "保存":
            save_button = widget
            break
    if save_button is not None and not getattr(save_button, "_cardproof_range_wrapped", False):
        original_command = save_button.cget("command")

        def _wrapped_save():
            self.config_data["order_range_mode"] = _normalize_order_range_mode(self.order_range_mode_var.get())
            self.config_data["order_range_days"] = int(self.order_range_days_var.get() or 0)
            self.config_data["order_range_start_date"] = str(self.order_range_start_date_var.get() or "").strip()
            self.config_data["order_range_start_time"] = str(self.order_range_start_time_var.get() or "").strip() or "00:00"
            save_button.tk.call(original_command)
            self.refresh_orders()

        save_button.configure(command=_wrapped_save)
        save_button._cardproof_range_wrapped = True

    dialog._cardproof_range_patched = True
    try:
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
    except Exception:
        pass


def _patched_open_settings_v2(self):
    _ensure_range_vars(self)
    existing = set(self.winfo_children())
    _orig_open_settings(self)
    self.update_idletasks()
    dialog = None
    for child in self.winfo_children():
        if child.winfo_class() == "Toplevel" and child not in existing:
            dialog = child
    dialog = dialog or _find_settings_dialog(self)
    if dialog is None or getattr(dialog, "_cardproof_range_patched_v2", False):
        return
    inner, canvas = _find_settings_inner_frame(dialog)
    if inner is None:
        return

    target_row = None
    for child in inner.winfo_children():
        info = child.grid_info()
        if info and child.winfo_class() == "Text":
            target_row = int(info.get("row", 0))
            break
    if target_row is None:
        target_row = max((int(child.grid_info().get("row", 0)) for child in inner.winfo_children() if child.grid_info()), default=0)

    for child in inner.winfo_children():
        info = child.grid_info()
        if info and int(info.get("row", 0)) >= target_row:
            child.grid_configure(row=int(info.get("row", 0)) + 2)

    row1 = ttk.Frame(inner, style="Panel.TFrame")
    row1.grid(row=target_row, column=0, sticky="ew", padx=14, pady=(8, 0))
    row1.columnconfigure(1, weight=1)
    ttk.Label(row1, text="查看范围").grid(row=0, column=0, sticky="w")
    ttk.Combobox(
        row1,
        textvariable=self.order_range_mode_var,
        values=tuple(ORDER_RANGE_LABELS.values()),
        state="readonly",
    ).grid(row=0, column=1, sticky="ew", padx=(12, 0))

    row2 = ttk.Frame(inner, style="Panel.TFrame")
    row2.grid(row=target_row + 1, column=0, sticky="ew", padx=14, pady=(8, 0))
    row2.columnconfigure(1, weight=1)
    row2.columnconfigure(3, weight=1)
    row2.columnconfigure(4, weight=1)
    ttk.Label(row2, text="近N天").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(row2, from_=0, to=3650, textvariable=self.order_range_days_var, width=8).grid(row=0, column=1, sticky="ew", padx=(12, 12))
    ttk.Label(row2, text="起始时间").grid(row=0, column=2, sticky="w")
    ttk.Entry(row2, textvariable=self.order_range_start_date_var, width=12).grid(row=0, column=3, sticky="ew", padx=(12, 8))
    ttk.Entry(row2, textvariable=self.order_range_start_time_var, width=8).grid(row=0, column=4, sticky="ew")

    buttons = [widget for widget in _iter_widgets(dialog) if widget.winfo_class() == "TButton"]
    save_button = buttons[-1] if buttons else None
    if save_button is not None and not getattr(save_button, "_cardproof_range_wrapped", False):
        original_command = save_button.cget("command")

        def _wrapped_save():
            self.config_data["order_range_mode"] = _normalize_order_range_mode(self.order_range_mode_var.get())
            self.config_data["order_range_days"] = int(self.order_range_days_var.get() or 0)
            self.config_data["order_range_start_date"] = str(self.order_range_start_date_var.get() or "").strip()
            self.config_data["order_range_start_time"] = str(self.order_range_start_time_var.get() or "").strip() or "00:00"
            save_button.tk.call(original_command)
            self.refresh_orders()

        save_button.configure(command=_wrapped_save)
        save_button._cardproof_range_wrapped = True

    dialog._cardproof_range_patched_v2 = True
    try:
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
    except Exception:
        pass


def _patched_version_paths(self, item):
    order_root, relative = self._local_backup_roots(item)
    relative_path = Path(relative)
    snapshot_file = order_root / "old" / ".versions" / relative_path
    old_file = order_root / "old" / relative_path.parent / _public_old_name(relative_path.name)
    return snapshot_file, old_file


def _patched_record_version_backup(self, item, data: bytes) -> None:
    if not item.local_path or not item.rel_path or not data:
        return
    try:
        snapshot_file, old_file = _patched_version_paths(self, item)
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.parent.mkdir(parents=True, exist_ok=True)

        previous = None
        previous_mtime = None
        if snapshot_file.exists():
            previous = mod.read_bytes_stable(snapshot_file)
            previous_mtime = snapshot_file.stat().st_mtime

        current_mtime = (item.modified_at or datetime.now().astimezone()).timestamp()
        if previous is None:
            mod.atomic_write_bytes(snapshot_file, data)
            os.utime(snapshot_file, (current_mtime, current_mtime))
            return

        if previous == data:
            return

        mod.atomic_write_bytes(old_file, previous)
        stamp = previous_mtime if previous_mtime is not None else max(0.0, current_mtime - 1.0)
        os.utime(old_file, (stamp, stamp))
        mod.atomic_write_bytes(snapshot_file, data)
        os.utime(snapshot_file, (current_mtime, current_mtime))
    except Exception:
        pass


def _patched_load_version_backup(self, item):
    if not item.local_path or not item.rel_path:
        return None
    try:
        _snapshot_file, old_file = _patched_version_paths(self, item)
        if not old_file.exists():
            return None
        data = mod.read_bytes_stable(old_file)
        modified_at = datetime.fromtimestamp(old_file.stat().st_mtime).astimezone()
        pair_key, face_label = _pair_info_from_name(item.name)
        return mod.FileItem(
            name=_public_old_name(item.name),
            rel_path=_old_rel_path(item.rel_path),
            modified_at=modified_at,
            size=len(data),
            source=item.source,
            local_path=str(old_file),
            mime_type=item.mime_type or "image/jpeg",
            data=data,
            physical_size_mm=mod.detect_physical_size_mm(data=data, local_path=str(old_file)),
            version_label="旧版",
            face_label=face_label or getattr(item, "face_label", None),
            pair_key=pair_key or getattr(item, "pair_key", None),
        )
    except Exception:
        return None


def _patched_prepare_display_files(self, items):
    def face_priority(item):
        pair_key, inferred_face = _pair_info_from_name(getattr(item, "name", ""))
        if not getattr(item, "pair_key", None):
            item.pair_key = pair_key or getattr(item, "pair_key", None)
        if not getattr(item, "face_label", None):
            item.face_label = inferred_face or getattr(item, "face_label", None)
        face = getattr(item, "face_label", None)
        if face == FACE_FRONT:
            return 0
        if face == FACE_BACK:
            return 1
        return 2

    ordered = sorted(
        items,
        key=lambda x: (
            face_priority(x),
            -((x.modified_at or datetime.min.replace(tzinfo=timezone.utc)).timestamp()),
        ),
    )
    for item in ordered:
        pair_key, face_label = _pair_info_from_name(item.name)
        item.pair_key = pair_key or getattr(item, "pair_key", None)
        item.face_label = face_label or getattr(item, "face_label", None)
        item.version_label = getattr(item, "version_label", None)
    return ordered


def _patched_build_proofread_items_v2(self, items, include_old: bool = True):
    prepared = _patched_prepare_display_files(self, list(items or []))
    result = []
    seen = set()

    def clone_with_data(item, version_label):
        rel_path = str(getattr(item, "rel_path", "") or getattr(item, "name", "") or "").replace("\\", "/")
        cache_key = (version_label, rel_path, str(getattr(item, "local_path", "") or ""))
        if cache_key in seen:
            return None
        data = getattr(item, "data", None)
        if not data:
            local_path = str(getattr(item, "local_path", "") or "").strip()
            if local_path:
                try:
                    data = mod.read_bytes_stable(Path(local_path))
                except Exception:
                    data = None
            if data is None and rel_path:
                try:
                    data = self.source.download(rel_path)
                except TypeError:
                    data = self.source.download(rel_path, None)
                except Exception:
                    data = None
        if not data:
            return None
        seen.add(cache_key)
        local_path = str(getattr(item, "local_path", "") or "").strip() or None
        return mod.FileItem(
            name=str(getattr(item, "name", "") or Path(rel_path).name or "image.jpg"),
            rel_path=rel_path or str(getattr(item, "name", "") or "image.jpg"),
            modified_at=getattr(item, "modified_at", None),
            size=len(data),
            source=str(getattr(item, "source", "local") or "local"),
            local_path=local_path,
            mime_type=str(getattr(item, "mime_type", "") or "image/jpeg"),
            data=data,
            physical_size_mm=mod.detect_physical_size_mm(data=data, local_path=local_path),
            version_label=version_label,
            face_label=getattr(item, "face_label", None),
            pair_key=getattr(item, "pair_key", None),
        )

    for item in prepared:
        current = clone_with_data(item, "\u6700\u65b0\u7248")
        if current is not None:
            result.append(current)
        if include_old:
            old_item = _patched_load_version_backup(self, item)
            if old_item is not None:
                old_ready = clone_with_data(old_item, "\u65e7\u7248")
                if old_ready is not None:
                    result.append(old_ready)
    return result


def _pick_latest_by_face(items, face_label):
    matches = [item for item in items if getattr(item, "face_label", None) == face_label]
    matches.sort(key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return matches[0] if matches else None


def _patched_latest_face_targets(self, items, mode):
    mode = (mode or "all").strip().lower()
    prepared = _patched_prepare_display_files(self, list(items or []))
    if not prepared:
        return []

    latest_by_face = {}
    for item in prepared:
        face = getattr(item, "face_label", None)
        if face not in {FACE_FRONT, FACE_BACK}:
            continue
        current = latest_by_face.get(face)
        current_mtime = getattr(current, "modified_at", None) if current else None
        item_mtime = getattr(item, "modified_at", None)
        if current is None or (item_mtime or datetime.min.replace(tzinfo=timezone.utc)) >= (current_mtime or datetime.min.replace(tzinfo=timezone.utc)):
            latest_by_face[face] = item

    front = latest_by_face.get(FACE_FRONT)
    back = latest_by_face.get(FACE_BACK)

    if front is None and back is None:
        latest_group = {}
        for item in prepared:
            key = getattr(item, "pair_key", None) or _normalize_compare_stem(item.name) or item.rel_path or item.name
            latest_group.setdefault(key, []).append(item)
        if latest_group:
            best_group = max(
                latest_group.values(),
                key=lambda group: max((entry.modified_at or datetime.min.replace(tzinfo=timezone.utc) for entry in group)),
            )
            best_group = sorted(best_group, key=lambda x: x.modified_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            front = _pick_latest_by_face(best_group, FACE_FRONT)
            back = _pick_latest_by_face(best_group, FACE_BACK)

    if mode == "front":
        return [front] if front else []
    if mode == "back":
        return [back] if back else []

    targets = []
    if front:
        targets.append(front)
    if back and (not front or back.rel_path != front.rel_path):
        targets.append(back)
    if not targets:
        targets.append(prepared[0])
    return targets


def _patched_build_prompt(self, source_text: str, notes: str, files: list, root_hint: str) -> str:
    file_lines = "\n".join(
        f"{idx + 1}. {item.name} | \u8def\u5f84: {item.rel_path or item.name} | \u65f6\u95f4: {mod.fmt_dt(item.modified_at)}"
        + (f" | \u5c3a\u5bf8: {item.physical_size_mm} mm" if item.physical_size_mm else "")
        for idx, item in enumerate(files)
    )
    naming_rules = (
        "\u547d\u540d\u89c4\u5219\uff1a\u4e0d\u5e26 old \u7684\u662f\u6700\u65b0\u7248\uff1b\u540c\u540d\u4e14\u5e26 old \u7684\u662f\u65e7\u7248\u3002"
        "\u6587\u4ef6\u540d\u672b\u5c3e\u6570\u5b57\u4e3a\u5947\u6570\u7684\u662f\u6b63\u9762\uff0c\u5076\u6570\u7684\u662f\u53cd\u9762\u3002"
        "\u5982\u679c\u6587\u4ef6\u540d\u91cc\u5305\u542b\u201c\u753b\u677f\u201d\u6216\u5176\u4ed6\u591a\u4f59\u7b26\u53f7\uff0c\u8bf7\u5ffd\u7565\u8fd9\u4e9b\u5dee\u5f02\uff0c\u53ea\u6309\u53bb\u6389 old \u540e\u7684\u540c\u540d\u6587\u4ef6\u5bf9\u6bd4\u3002"
    )
    layout_rules = (
        "\u8bf7\u5148\u68c0\u67e5\u65b0\u7248\u548c\u65e7\u7248\u7684\u7248\u5f0f\u5dee\u5f02\uff1a\u4f4d\u7f6e\u3001\u5bf9\u9f50\u3001\u5b57\u53f7\u3001\u884c\u8ddd\u3001\u7559\u767d\u3001 logo\u3001\u4e8c\u7ef4\u7801\u3001\u7535\u8bdd\u56fe\u6807\u3001\u5730\u5740\u884c\u3001\u80cc\u9762\u4fe1\u606f\u662f\u5426\u7f3a\u5931\u6216\u504f\u79fb\u3002"
        "\u5e03\u5c40\u5dee\u5f02\u548c\u5143\u7d20\u7f3a\u5931\u5fc5\u987b\u5355\u72ec\u5199\u5165 missing_or_changed_elements\u3002"
        "\u6587\u5b57\u9519\u8bef\u53ea\u4ee5\u5ba2\u6237\u539f\u59cb\u6587\u5b57\u4e3a\u51c6\uff0c\u4e0d\u8981\u628a\u65e7\u7248\u5f53\u6210\u6587\u5b57\u6807\u51c6\u3002"
        "\u786e\u5b9a\u9519\u8bef\u653e\u5165 must_fix\uff0c\u7591\u4f3c\u95ee\u9898\u653e\u5165 confirm\uff0c\u7248\u5f0f\u53d8\u5316\u4e0e\u5143\u7d20\u7f3a\u5931\u653e\u5165 missing_or_changed_elements\u3002"
        "\u6240\u6709\u8f93\u51fa\u4e00\u5b9a\u7528\u4e2d\u6587\uff0c\u5e76\u6309\u91cd\u8981\u7a0b\u5ea6\u6392\u5e8f\u3002"
    )
    template = self.proofread_prompt or mod.DEFAULT_PROOFREAD_PROMPT
    return (
        template.replace("[[ROOT_HINT]]", root_hint or "[\u672a\u63d0\u4f9b]")
        .replace("[[SOURCE_TEXT]]", source_text or "[\u672a\u63d0\u4f9b]")
        .replace("[[NOTES]]", notes or "[\u65e0]")
        .replace("[[CUSTOM_PROMPT]]", (self.custom_prompt or "[\u65e0]") + "\n\n" + naming_rules + "\n\n" + layout_rules)
        .replace("[[FILE_LINES]]", file_lines or "[\u65e0]")
    )

def _run_scope_proofread(self, source_items, mode):
    targets = _patched_latest_face_targets(self, source_items, mode)
    files = self._build_proofread_items(targets, include_old=True)
    return self._proofread_items(files, self._current_root_hint())


def _patched_check_selected_order(self):
    if not self.selected_order:
        mod.messagebox.showinfo("提示", "请先选择一个订单")
        return
    mode = getattr(self, "proofread_face_mode_var", None).get() if hasattr(self, "proofread_face_mode_var") else "all"
    scope_label = {"all": "全部", "front": "正面", "back": "反面"}.get(mode, "全部")
    self.set_status(f"正在检查订单：{self.selected_order.order_id} ({scope_label})")

    def worker():
        source_items = self.current_display_files or self.selected_order.files
        return _run_scope_proofread(self, source_items, mode)

    self._run_bg(worker, self.on_report, self.on_error)


def _patched_check_latest_print_standard(self):
    if not self.selected_order and not self.manual_files:
        mod.messagebox.showinfo("提示", "请先选择一个订单")
        return
    if self._auto_check_running:
        self.set_status("正在检测，请稍候")
        return
    source_items = self.current_display_files or self.manual_files or self.selected_order.files
    if not source_items:
        mod.messagebox.showinfo("提示", "当前没有可检测的文件")
        return
    mode = getattr(self, "proofread_face_mode_var", None).get() if hasattr(self, "proofread_face_mode_var") else "all"
    scope_label = {"all": "全部", "front": "正面", "back": "反面"}.get(mode, "全部")
    self.set_status(f"正在检测最新文件：{scope_label}")

    def worker():
        return _run_scope_proofread(self, source_items, mode)

    self._run_bg(worker, self.on_report, self.on_error)

for client_name in ("WebDavClient", "OpenListBrowserClient", "LocalFolderClient"):
    client = getattr(mod, client_name, None)
    if client is not None:
        _patch_source_client(client)

mod.ProofApp._build_left = _orig_build_left
mod.ProofApp.open_settings = _patched_open_settings_v2
mod.ProofApp.refresh_orders = _refresh_orders
mod.ProofApp._resolve_order_cutoff = _resolve_order_cutoff
mod.ProofApp._record_version_backup = _patched_record_version_backup
mod.ProofApp._load_version_backup = _patched_load_version_backup
mod.ProofApp._prepare_display_files = _patched_prepare_display_files
mod.ProofApp._build_proofread_items = _patched_build_proofread_items_v2
mod.ProofApp._latest_face_targets = _patched_latest_face_targets
mod.ProofApp.check_selected_order = _patched_check_selected_order
mod.ProofApp.check_latest_print_standard = _patched_check_latest_print_standard
mod.OpenAIClient.build_prompt = _patched_build_prompt
mod.face_label_from_name = _pair_info_from_name
mod.FACE_FRONT = FACE_FRONT
mod.FACE_BACK = FACE_BACK


DEFAULT_CONFIG.setdefault("old_watch_enabled", True)
DEFAULT_CONFIG.setdefault("old_seed_days", 1)
DEFAULT_CONFIG.setdefault("old_prune_days", 30)
DEFAULT_CONFIG.setdefault("launch_at_startup", False)
mod.DEFAULT_CONFIG = DEFAULT_CONFIG

AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "CardProof"
WATCH_INTERVAL_SECONDS = 2.5

_orig_proofapp_init = mod.ProofApp.__init__
_orig_proofapp_close = mod.ProofApp._on_close


def _range_mode_to_key(value: str | None) -> str:
    reverse = {label: key for key, label in ORDER_RANGE_LABELS.items()}
    raw = str(value or "").strip()
    return reverse.get(raw, raw if raw in ORDER_RANGE_LABELS else "today")


def _source_is_local(self) -> bool:
    return str(self.config_data.get("source_mode", "local")).strip().lower() == "local"


def _source_root_path(self) -> Path | None:
    raw = str(self.config_data.get("local_root", "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def _iter_source_jpg_files(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        name = entry.name
                        if entry.is_dir(follow_symlinks=False):
                            if name in {"old", ".cardproof"} or name.startswith(".cardproof"):
                                continue
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        lower_name = name.lower()
                        if lower_name.endswith((".jpg", ".jpeg")) and "old" not in Path(name).stem.lower():
                            yield Path(entry.path), entry.stat(follow_symlinks=False)
                    except Exception:
                        continue
        except Exception:
            continue


def _scan_old_dirs(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            path = Path(entry.path)
                            if entry.name == "old":
                                yield path
                                continue
                            if entry.name.startswith(".cardproof"):
                                continue
                            stack.append(path)
                    except Exception:
                        continue
        except Exception:
            continue


def _apply_autostart(self) -> None:
    try:
        enabled = bool(self.config_data.get("launch_at_startup", False))
        exe_path = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).resolve()
        command = f'"{exe_path}"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_ALL_ACCESS) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def _prune_old_files(self, root: Path) -> None:
    days = int(self.config_data.get("old_prune_days", DEFAULT_CONFIG.get("old_prune_days", 30)) or 0)
    if days <= 0:
        return
    cutoff = time.time() - days * 86400
    for old_dir in _scan_old_dirs(root):
        try:
            for path in old_dir.rglob("*"):
                try:
                    if not path.is_file():
                        continue
                    if path.name.lower().endswith((".jpg", ".jpeg")) and path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except Exception:
                    continue
        except Exception:
            continue


def _old_watch_maintain_once(self) -> None:
    if not _source_is_local(self):
        return
    root = _source_root_path(self)
    if root is None or not root.exists():
        return
    state = getattr(self, "_old_watch_state", {})
    seen = set()
    seed_days = int(self.config_data.get("old_seed_days", DEFAULT_CONFIG.get("old_seed_days", 1)) or 0)
    seed_cutoff = datetime.now().astimezone() - timedelta(days=max(seed_days, 0))
    for file_path, stat in _iter_source_jpg_files(root):
        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        seen.add(rel_path)
        modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
        current_sig = (stat.st_size, stat.st_mtime)
        previous_sig = state.get(rel_path)
        item = mod.FileItem(
            name=file_path.name,
            rel_path=rel_path,
            modified_at=modified_at,
            size=stat.st_size,
            source="local",
            local_path=str(file_path),
            mime_type=mimetypes.guess_type(file_path.name)[0] or "image/jpeg",
        )
        should_seed = previous_sig is None and (seed_days <= 0 or modified_at >= seed_cutoff)
        should_update = previous_sig is not None and previous_sig != current_sig
        if should_seed or should_update:
            try:
                data = mod.read_bytes_stable(file_path)
                self._record_version_backup(item, data)
            except Exception:
                pass
        state[rel_path] = current_sig
    stale = [key for key in state.keys() if key not in seen]
    for key in stale:
        state.pop(key, None)
    self._old_watch_state = state
    _prune_old_files(self, root)


def _old_watch_loop(self) -> None:
    stop_event = getattr(self, "_old_watch_stop", None)
    if stop_event is None:
        return
    while not stop_event.wait(WATCH_INTERVAL_SECONDS):
        try:
            _old_watch_maintain_once(self)
        except Exception:
            continue


def _start_old_watch(self) -> None:
    if not bool(self.config_data.get("old_watch_enabled", DEFAULT_CONFIG.get("old_watch_enabled", True))):
        return
    if not _source_is_local(self):
        return
    thread = getattr(self, "_old_watch_thread", None)
def _prefix_report(scope: str, report: dict) -> dict:
    scope_text = str(scope or "").strip() or "\u6b63\u9762"
    result = {
        "summary": f"{scope_text}：{str(report.get('summary', '') or '').strip()}",
        "recognized_text": [f"【{scope_text}】{text}" for text in (report.get("recognized_text") or [])],
        "must_fix": [],
        "confirm": [],
        "looks_ok": [f"【{scope_text}】{text}" for text in (report.get("looks_ok") or [])],
        "missing_or_changed_elements": [],
        "prepress_risks": [],
    }
    for key in ("must_fix", "confirm", "missing_or_changed_elements", "prepress_risks"):
        for item in (report.get(key) or []):
            if isinstance(item, dict):
                patched = dict(item)
                patched["title"] = f"【{scope_text}】{patched.get('title', '')}".strip()
                result[key].append(patched)
    return result


def _merge_reports(*reports: dict) -> dict:
    summaries = [str(report.get("summary", "") or "").strip() for report in reports if report]
    merged = {
        "summary": "；".join([text for text in summaries if text]) or "\u6682\u65e0",
        "recognized_text": [],
        "must_fix": [],
        "confirm": [],
        "looks_ok": [],
        "missing_or_changed_elements": [],
        "prepress_risks": [],
    }
    for report in reports:
        if not report:
            continue
        for key in merged.keys():
            if key == "summary":
                continue
            merged[key].extend(report.get(key) or [])
    return merged


def _proofread_face_scope(self, source_items, mode: str, emit_intermediate: bool = False):
    mode = (mode or "front").strip().lower()
    root_hint = self._current_root_hint()
    if mode in {"front", "back"}:
        targets = _patched_latest_face_targets(self, source_items, mode)
        files = self._build_proofread_items(targets, include_old=True)
        return self._proofread_items(files, root_hint)

    front_targets = _patched_latest_face_targets(self, source_items, "front")
    back_targets = _patched_latest_face_targets(self, source_items, "back")
    front_report = None
    back_report = None
    if front_targets:
        front_files = self._build_proofread_items(front_targets, include_old=True)
        front_report = _prefix_report("\u6b63\u9762", self._proofread_items(front_files, root_hint))
        if emit_intermediate:
            try:
                self.after(0, lambda report=front_report: self._render_report(report))
            except Exception:
                pass
    if back_targets:
        back_files = self._build_proofread_items(back_targets, include_old=True)
        back_report = _prefix_report("\u53cd\u9762", self._proofread_items(back_files, root_hint))
    return _merge_reports(front_report or {}, back_report or {})


def _patched_check_selected_order_v2(self):
    if not self.selected_order:
        mod.messagebox.showinfo("\u63d0\u793a", "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u8ba2\u5355")
        return
    mode = getattr(self, "proofread_face_mode_var", None).get() if hasattr(self, "proofread_face_mode_var") else "front"
    label = {"front": "\u6b63\u9762", "back": "\u53cd\u9762", "all": "\u5168\u90e8"}.get(mode, "\u6b63\u9762")
    self.set_status(f"\u6b63\u5728\u68c0\u67e5\u8ba2\u5355\uff1a{self.selected_order.order_id} ({label})")

    def worker():
        source_items = self.current_display_files or self.selected_order.files
        return _proofread_face_scope(self, source_items, mode, emit_intermediate=(mode == "all"))

    self._run_bg(worker, self.on_report, self.on_error)


def _patched_check_latest_print_standard_v2(self):
    if not self.selected_order and not self.manual_files:
        mod.messagebox.showinfo("\u63d0\u793a", "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u8ba2\u5355")
        return
    if self._auto_check_running:
        self.set_status("\u6b63\u5728\u68c0\u6d4b\uff0c\u8bf7\u7a0d\u5019")
        return
    source_items = self.current_display_files or self.manual_files or self.selected_order.files
    if not source_items:
        mod.messagebox.showinfo("\u63d0\u793a", "\u5f53\u524d\u6ca1\u6709\u53ef\u68c0\u6d4b\u7684\u6587\u4ef6")
        return
    mode = getattr(self, "proofread_face_mode_var", None).get() if hasattr(self, "proofread_face_mode_var") else "front"
    label = {"front": "\u6b63\u9762", "back": "\u53cd\u9762", "all": "\u5168\u90e8"}.get(mode, "\u6b63\u9762")
    self.set_status(f"\u6b63\u5728\u68c0\u6d4b\u6700\u65b0\u6587\u4ef6\uff1a{label}")

    def worker():
        return _proofread_face_scope(self, source_items, mode, emit_intermediate=(mode == "all"))

    self._run_bg(worker, self.on_report, self.on_error)

def _patched_open_settings_v4(self):
    _ensure_range_vars(self)
    config = _normalize_loaded_config(self.config_data)

    existing = getattr(self, "_cardproof_settings_dialog", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

    def as_int(value, default, minimum=0):
        try:
            return max(minimum, int(str(value).strip() or default))
        except Exception:
            return max(minimum, int(default))

    def make_labeled_row(parent, row, label, variable=None, show=None, width=0):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=label, width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
        entry = ttk.Entry(frame, textvariable=variable, show=show, width=width or 32)
        entry.grid(row=0, column=1, sticky="ew")
        return frame, entry

    def rebuild_runtime():
        mode = str(self.config_data.get("source_mode", "local") or "local").strip().lower()
        if mode == "webdav":
            self.source = mod.WebDavClient(
                str(self.config_data.get("dav_url", "") or "").strip(),
                str(self.config_data.get("dav_user", "") or "").strip(),
                str(self.config_data.get("dav_pass", "") or "").strip(),
                str(self.config_data.get("cache_dir", "") or "").strip() or None,
            )
        else:
            local_root = str(self.config_data.get("local_root", "") or "").strip() or str(APP_DIR)
            self.source = mod.LocalFolderClient(local_root)
        self.openai = mod.OpenAIClient(
            str(self.config_data.get("openai_base_url", "") or "").strip(),
            str(self.config_data.get("openai_api_key", "") or "").strip(),
            str(self.config_data.get("openai_model", "") or "").strip(),
            str(self.config_data.get("api_mode", "auto") or "auto").strip(),
            str(self.config_data.get("api_auth_style", "dual") or "dual").strip(),
            str(self.config_data.get("proofread_prompt", "") or ""),
            str(self.config_data.get("custom_prompt", "") or ""),
        )

    dialog = tk.Toplevel(self)
    dialog.title("\u8bbe\u7f6e")
    dialog.geometry("760x680")
    dialog.minsize(680, 540)
    dialog.transient(self)
    dialog.columnconfigure(0, weight=1)
    dialog.rowconfigure(0, weight=1)
    self._cardproof_settings_dialog = dialog

    outer = ttk.Frame(dialog, padding=(14, 14, 14, 10))
    outer.grid(row=0, column=0, sticky="nsew")
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)
    outer.rowconfigure(1, weight=0)

    canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    body = ttk.Frame(canvas, padding=(4, 2, 4, 2))
    body.columnconfigure(0, weight=1)
    canvas_window = canvas.create_window((0, 0), window=body, anchor="nw")

    def sync_scrollregion(_event=None):
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(canvas_window, width=canvas.winfo_width())
        except Exception:
            pass

    def on_mousewheel(event):
        try:
            delta = event.delta
            if delta == 0:
                return
            canvas.yview_scroll(int(-delta / 120), "units")
        except Exception:
            pass

    body.bind("<Configure>", sync_scrollregion)
    canvas.bind("<Configure>", sync_scrollregion)
    dialog.bind("<MouseWheel>", on_mousewheel)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())

    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    row = 0
    ttk.Label(body, text="\u63a5\u53e3", style="Header.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 8))
    row += 1

    provider_map = {value: key for key, value in API_PROVIDER_LABELS.items()}
    api_provider_var = tk.StringVar(value=API_PROVIDER_LABELS.get(_normalize_api_provider(config.get("openai_provider")), API_PROVIDER_LABELS["builtin"]))
    api_base_url_var = tk.StringVar(value=str(config.get("openai_custom_base_url") or config.get("openai_base_url") or _resolve_api_base_url(config.get("openai_provider"))))
    api_key_var = tk.StringVar(value=str(config.get("openai_api_key", "") or ""))
    model_var = tk.StringVar(value=str(config.get("openai_model", "") or ""))
    api_mode_var = tk.StringVar(value=str(config.get("api_mode", "auto") or "auto"))
    auth_style_var = tk.StringVar(value=str(config.get("api_auth_style", "dual") or "dual"))
    model_list_var = tk.StringVar(value="")
    model_values = []

    api_provider_row = ttk.Frame(body)
    api_provider_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    api_provider_row.columnconfigure(1, weight=1)
    ttk.Label(api_provider_row, text="API\u6765\u6e90", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    api_provider_box = ttk.Combobox(
        api_provider_row,
        textvariable=api_provider_var,
        values=tuple(API_PROVIDER_LABELS.values()),
        state="readonly",
        width=20,
    )
    api_provider_box.grid(row=0, column=1, sticky="ew")
    row += 1

    _, base_url_entry = make_labeled_row(body, row, "API Base URL", api_base_url_var)
    row += 1
    make_labeled_row(body, row, "API Key", api_key_var, show="*")
    row += 1

    model_row = ttk.Frame(body)
    model_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    model_row.columnconfigure(1, weight=1)
    ttk.Label(model_row, text="\u6a21\u578b", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    model_box = ttk.Combobox(model_row, textvariable=model_var, values=(), width=32)
    model_box.grid(row=0, column=1, sticky="ew")

    def apply_model_values(values):
        cleaned = []
        seen = set()
        current = str(model_var.get() or "").strip()
        if current:
            seen.add(current)
            cleaned.append(current)
        for value in values or []:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                cleaned.append(text)
        model_box.configure(values=tuple(cleaned))
        model_values[:] = cleaned

    def sync_model_placeholder():
        provider_key = provider_map.get(api_provider_var.get(), "builtin")
        current = str(model_var.get() or "").strip()
        if not current:
            default_model = _resolve_default_model(provider_key)
            if default_model:
                model_var.set(default_model)
        apply_model_values(model_values)

    def fetch_models():
        provider_key = provider_map.get(api_provider_var.get(), "builtin")
        base_url = _resolve_api_base_url(provider_key, api_base_url_var.get())
        api_key = str(api_key_var.get() or "").strip()
        auth_style = str(auth_style_var.get() or "dual").strip() or "dual"
        if not base_url:
            mod.messagebox.showwarning("\u63d0\u793a", "\u8bf7\u5148\u586b\u5199 API Base URL")
            return

        fetch_button.configure(state="disabled")
        model_list_var.set("\u6b63\u5728\u83b7\u53d6\u6a21\u578b...")

        def worker():
            return _fetch_remote_models(base_url, api_key, auth_style)

        def on_success(values):
            fetch_button.configure(state="normal")
            apply_model_values(values)
            if values:
                if str(model_var.get() or "").strip() not in values:
                    model_var.set(values[0])
                model_list_var.set(f"\u5df2\u83b7\u53d6 {len(values)} \u4e2a\u6a21\u578b")
            else:
                model_list_var.set("\u63a5\u53e3\u5df2\u8fde\u63a5\uff0c\u4f46\u672a\u8fd4\u56de\u6a21\u578b")

        def on_failure(exc):
            fetch_button.configure(state="normal")
            model_list_var.set("\u83b7\u53d6\u5931\u8d25")
            mod.messagebox.showerror(
                "\u83b7\u53d6\u6a21\u578b\u5931\u8d25",
                "\u8bf7\u68c0\u67e5 Base URL\u3001API Key\u3001\u63a5\u53e3\u6a21\u5f0f\u6216\u8ba4\u8bc1\u65b9\u5f0f\u3002\n\n"
                + str(exc),
            )

        self._run_bg(worker, on_success, on_failure)

    fetch_button = ttk.Button(model_row, text="\u83b7\u53d6\u6a21\u578b", command=fetch_models, width=10)
    fetch_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
    ttk.Label(model_row, textvariable=model_list_var).grid(row=1, column=1, columnspan=2, sticky="w", pady=(4, 0))
    row += 1

    mode_row = ttk.Frame(body)
    mode_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    mode_row.columnconfigure(1, weight=1)
    mode_row.columnconfigure(3, weight=1)
    ttk.Label(mode_row, text="\u63a5\u53e3\u6a21\u5f0f", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Combobox(mode_row, textvariable=api_mode_var, values=("auto", "chat", "responses"), state="readonly", width=14).grid(row=0, column=1, sticky="w")
    ttk.Label(mode_row, text="\u8ba4\u8bc1\u65b9\u5f0f").grid(row=0, column=2, sticky="e", padx=(14, 10))
    ttk.Combobox(mode_row, textvariable=auth_style_var, values=("dual", "bearer", "api-key"), state="readonly", width=14).grid(row=0, column=3, sticky="w")
    row += 1

    ttk.Separator(body, orient="horizontal").grid(row=row, column=0, sticky="ew", pady=(4, 12))
    row += 1

    ttk.Label(body, text="\u6587\u4ef6\u6765\u6e90", style="Header.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 8))
    row += 1

    source_mode_var = tk.StringVar(value="\u672c\u5730\u76ee\u5f55" if str(config.get("source_mode", "local")).lower() == "local" else "WebDAV")
    source_row = ttk.Frame(body)
    source_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    source_row.columnconfigure(1, weight=1)
    ttk.Label(source_row, text="\u6587\u4ef6\u6765\u6e90", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    source_box = ttk.Combobox(source_row, textvariable=source_mode_var, values=("\u672c\u5730\u76ee\u5f55", "WebDAV"), state="readonly", width=20)
    source_box.grid(row=0, column=1, sticky="w")
    row += 1

    source_stack = ttk.Frame(body)
    source_stack.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    source_stack.columnconfigure(0, weight=1)
    row += 1

    local_root_var = tk.StringVar(value=str(config.get("local_root", "") or ""))
    dav_url_var = tk.StringVar(value=str(config.get("dav_url", "") or ""))
    dav_user_var = tk.StringVar(value=str(config.get("dav_user", "") or ""))
    dav_pass_var = tk.StringVar(value=str(config.get("dav_pass", "") or ""))

    local_frame = ttk.Frame(source_stack)
    local_frame.columnconfigure(1, weight=1)
    ttk.Label(local_frame, text="\u672c\u5730\u76ee\u5f55", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    local_entry = ttk.Entry(local_frame, textvariable=local_root_var)
    local_entry.grid(row=0, column=1, sticky="ew")
    ttk.Button(
        local_frame,
        text="\u9009\u62e9",
        command=lambda: (
            lambda picked=mod.filedialog.askdirectory(initialdir=str(Path(local_root_var.get() or APP_DIR).parent if str(local_root_var.get() or "").strip() else APP_DIR)):
                local_root_var.set(picked or local_root_var.get())
        )(),
    ).grid(row=0, column=2, sticky="w", padx=(8, 0))

    webdav_frame = ttk.Frame(source_stack)
    webdav_frame.columnconfigure(1, weight=1)
    ttk.Label(webdav_frame, text="WebDAV URL", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Entry(webdav_frame, textvariable=dav_url_var).grid(row=0, column=1, sticky="ew")
    ttk.Label(webdav_frame, text="\u8d26\u53f7", width=12).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
    ttk.Entry(webdav_frame, textvariable=dav_user_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))
    ttk.Label(webdav_frame, text="\u5bc6\u7801", width=12).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
    ttk.Entry(webdav_frame, textvariable=dav_pass_var, show="*").grid(row=2, column=1, sticky="ew", pady=(8, 0))

    ttk.Separator(body, orient="horizontal").grid(row=row, column=0, sticky="ew", pady=(4, 12))
    row += 1

    ttk.Label(body, text="\u663e\u793a\u4e0e\u68c0\u67e5", style="Header.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 8))
    row += 1

    display_font_var = tk.StringVar(value=str(config.get("display_font", "system") or "system"))
    image_viewer_var = tk.StringVar(value=str(config.get("image_viewer", "builtin") or "builtin"))
    file_list_height_var = tk.IntVar(value=as_int(config.get("file_list_height", 11), 11, 6))
    hotkey_var = tk.StringVar(value=str(config.get("global_hotkey", "Ctrl+Alt+P") or "Ctrl+Alt+P"))

    display_row = ttk.Frame(body)
    display_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    display_row.columnconfigure(1, weight=1)
    display_row.columnconfigure(3, weight=1)
    ttk.Label(display_row, text="\u663e\u793a\u5b57\u4f53", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Combobox(display_row, textvariable=display_font_var, values=("system", "yahei", "songti"), state="readonly", width=14).grid(row=0, column=1, sticky="w")
    ttk.Label(display_row, text="\u56fe\u7247\u67e5\u770b").grid(row=0, column=2, sticky="e", padx=(14, 10))
    ttk.Combobox(display_row, textvariable=image_viewer_var, values=("builtin", "system"), state="readonly", width=14).grid(row=0, column=3, sticky="w")
    row += 1

    list_row = ttk.Frame(body)
    list_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    list_row.columnconfigure(1, weight=1)
    list_row.columnconfigure(3, weight=1)
    ttk.Label(list_row, text="\u6587\u4ef6\u5217\u8868\u9ad8\u5ea6", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Spinbox(list_row, from_=6, to=24, textvariable=file_list_height_var, width=8).grid(row=0, column=1, sticky="w")
    ttk.Label(list_row, text="\u5168\u5c40\u5feb\u6377\u952e").grid(row=0, column=2, sticky="e", padx=(14, 10))
    ttk.Entry(list_row, textvariable=hotkey_var, width=18).grid(row=0, column=3, sticky="w")
    row += 1

    range_mode_var = tk.StringVar(value=ORDER_RANGE_LABELS.get(_normalize_order_range_mode(config.get("order_range_mode")), ORDER_RANGE_LABELS["days"]))
    range_days_var = tk.IntVar(value=as_int(config.get("order_range_days", 2), 2, 0))
    range_date_var = tk.StringVar(value=str(config.get("order_range_start_date", "") or ""))
    range_time_var = tk.StringVar(value=str(config.get("order_range_start_time", "00:00") or "00:00"))

    range_row = ttk.Frame(body)
    range_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    range_row.columnconfigure(1, weight=1)
    ttk.Label(range_row, text="\u67e5\u770b\u8303\u56f4", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Combobox(range_row, textvariable=range_mode_var, values=tuple(ORDER_RANGE_LABELS.values()), state="readonly", width=16).grid(row=0, column=1, sticky="w")
    ttk.Label(range_row, text="\u8fd1N\u5929", width=8).grid(row=0, column=2, sticky="e", padx=(14, 10))
    ttk.Spinbox(range_row, from_=0, to=3650, textvariable=range_days_var, width=8).grid(row=0, column=3, sticky="w")
    row += 1

    since_row = ttk.Frame(body)
    since_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(since_row, text="\u81ea\u5b9a\u4e49\u8d77\u59cb", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Entry(since_row, textvariable=range_date_var, width=16).grid(row=0, column=1, sticky="w")
    ttk.Entry(since_row, textvariable=range_time_var, width=8).grid(row=0, column=2, sticky="w", padx=(8, 0))
    row += 1

    old_watch_enabled_var = tk.BooleanVar(value=bool(config.get("old_watch_enabled", DEFAULT_CONFIG["old_watch_enabled"])))
    old_seed_days_var = tk.IntVar(value=as_int(config.get("old_seed_days", DEFAULT_CONFIG["old_seed_days"]), DEFAULT_CONFIG["old_seed_days"], 0))
    old_prune_days_var = tk.IntVar(value=as_int(config.get("old_prune_days", DEFAULT_CONFIG["old_prune_days"]), DEFAULT_CONFIG["old_prune_days"], 0))
    launch_at_startup_var = tk.BooleanVar(value=bool(config.get("launch_at_startup", DEFAULT_CONFIG["launch_at_startup"])))

    watch_row = ttk.Frame(body)
    watch_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    ttk.Checkbutton(watch_row, text="\u540e\u53f0\u76d1\u542c\u5e76\u751f\u6210 old", variable=old_watch_enabled_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(watch_row, text="\u5f00\u673a\u81ea\u542f\u52a8", variable=launch_at_startup_var).grid(row=0, column=1, sticky="w", padx=(18, 0))
    row += 1

    old_row = ttk.Frame(body)
    old_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
    old_row.columnconfigure(1, weight=1)
    old_row.columnconfigure(3, weight=1)
    ttk.Label(old_row, text="old\u9884\u7559\u5929\u6570", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Spinbox(old_row, from_=0, to=3650, textvariable=old_seed_days_var, width=8).grid(row=0, column=1, sticky="w")
    ttk.Label(old_row, text="\u8fc7\u671f\u6e05\u7406").grid(row=0, column=2, sticky="e", padx=(14, 10))
    ttk.Spinbox(old_row, from_=0, to=3650, textvariable=old_prune_days_var, width=8).grid(row=0, column=3, sticky="w")
    row += 1

    ttk.Separator(body, orient="horizontal").grid(row=row, column=0, sticky="ew", pady=(4, 12))
    row += 1

    ttk.Label(body, text="\u63d0\u793a\u8bcd", style="Header.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 8))
    row += 1

    prompt_frame = ttk.Frame(body)
    prompt_frame.grid(row=row, column=0, sticky="nsew", pady=(0, 8))
    prompt_frame.columnconfigure(0, weight=1)
    ttk.Label(prompt_frame, text="\u9ed8\u8ba4\u6838\u7a3f\u63d0\u793a\u8bcd").grid(row=0, column=0, sticky="w", pady=(0, 4))
    proofread_prompt_text = tk.Text(prompt_frame, height=8, wrap="word")
    proofread_prompt_text.grid(row=1, column=0, sticky="ew")
    proofread_prompt_text.insert(
        "1.0",
        str(
            config.get("proofread_prompt")
            or getattr(self.openai, "proofread_prompt", "")
            or getattr(mod, "DEFAULT_PROOFREAD_PROMPT", "")
            or ""
        ),
    )
    ttk.Label(prompt_frame, text="\u81ea\u5b9a\u4e49\u63d0\u793a\u8bcd").grid(row=2, column=0, sticky="w", pady=(8, 4))
    custom_prompt_text = tk.Text(prompt_frame, height=5, wrap="word")
    custom_prompt_text.grid(row=3, column=0, sticky="ew")
    custom_prompt_text.insert("1.0", str(config.get("custom_prompt", getattr(self.openai, "custom_prompt", "")) or ""))
    row += 1

    buttons = ttk.Frame(body)
    buttons.grid(row=row, column=0, sticky="ew", pady=(10, 0))
    buttons.columnconfigure(0, weight=1)
    ttk.Button(buttons, text="\u53d6\u6d88", command=dialog.destroy).grid(row=0, column=1, sticky="e")

    def sync_api_provider(*_args):
        provider_key = provider_map.get(api_provider_var.get(), "builtin")
        if provider_key == "custom":
            base_url_entry.configure(state="normal")
            if not str(api_base_url_var.get() or "").strip():
                api_base_url_var.set(API_PROVIDER_URLS["builtin"])
        else:
            api_base_url_var.set(API_PROVIDER_URLS.get(provider_key, API_PROVIDER_URLS["builtin"]))
            base_url_entry.configure(state="readonly")
        sync_model_placeholder()

    def sync_source_mode(*_args):
        mode_label = source_mode_var.get()
        local_frame.grid_forget()
        webdav_frame.grid_forget()
        if mode_label == "WebDAV":
            webdav_frame.grid(row=0, column=0, sticky="ew")
        else:
            local_frame.grid(row=0, column=0, sticky="ew")
        sync_scrollregion()

    def sync_range_mode(*_args):
        mode_key = _range_mode_to_key(range_mode_var.get())
        if mode_key == "since":
            since_row.grid()
        else:
            since_row.grid_remove()
        sync_scrollregion()

    def save_settings():
        if getattr(dialog, "_cardproof_saving", False):
            return
        dialog._cardproof_saving = True
        try:
            provider_key = provider_map.get(api_provider_var.get(), "builtin")
            source_key = "webdav" if source_mode_var.get() == "WebDAV" else "local"
            next_config = dict(self.config_data)
            next_config.update({
                "openai_provider": provider_key,
                "openai_custom_base_url": str(api_base_url_var.get() or "").strip() if provider_key == "custom" else "",
                "openai_base_url": _resolve_api_base_url(provider_key, api_base_url_var.get()),
                "openai_api_key": str(api_key_var.get() or "").strip(),
                "openai_model": str(model_var.get() or "").strip() or _resolve_default_model(provider_key),
                "api_mode": str(api_mode_var.get() or "auto").strip() or "auto",
                "api_auth_style": str(auth_style_var.get() or "dual").strip() or "dual",
                "source_mode": source_key,
                "local_root": str(local_root_var.get() or "").strip(),
                "dav_url": str(dav_url_var.get() or "").strip(),
                "dav_user": str(dav_user_var.get() or "").strip(),
                "dav_pass": str(dav_pass_var.get() or "").strip(),
                "display_font": str(display_font_var.get() or "system").strip() or "system",
                "image_viewer": str(image_viewer_var.get() or "builtin").strip() or "builtin",
                "file_list_height": as_int(file_list_height_var.get(), 11, 6),
                "global_hotkey": str(hotkey_var.get() or "Ctrl+Alt+P").strip() or "Ctrl+Alt+P",
                "order_range_mode": _range_mode_to_key(range_mode_var.get()),
                "order_range_days": as_int(range_days_var.get(), 2, 0),
                "order_range_start_date": str(range_date_var.get() or "").strip(),
                "order_range_start_time": str(range_time_var.get() or "").strip() or "00:00",
                "old_watch_enabled": bool(old_watch_enabled_var.get()),
                "old_seed_days": as_int(old_seed_days_var.get(), DEFAULT_CONFIG["old_seed_days"], 0),
                "old_prune_days": as_int(old_prune_days_var.get(), DEFAULT_CONFIG["old_prune_days"], 0),
                "launch_at_startup": bool(launch_at_startup_var.get()),
                "proofread_prompt": proofread_prompt_text.get("1.0", "end-1c"),
                "custom_prompt": custom_prompt_text.get("1.0", "end-1c"),
                "auto_sync_old_files": False,
            })
            next_config.pop("sync_target_root", None)
            next_config.pop("sync_interval_minutes", None)
            if source_key == "local":
                next_config["cache_dir"] = _default_local_cache_dir(next_config.get("local_root"))
            next_config = _normalize_loaded_config(next_config)

            mod.save_config(next_config)
            self.config_data = next_config

            self.order_range_mode_var.set(ORDER_RANGE_LABELS.get(self.config_data.get("order_range_mode", "days"), ORDER_RANGE_LABELS["days"]))
            self.order_range_days_var.set(int(self.config_data.get("order_range_days", 2)))
            self.order_range_start_date_var.set(str(self.config_data.get("order_range_start_date", "") or ""))
            self.order_range_start_time_var.set(str(self.config_data.get("order_range_start_time", "00:00") or "00:00"))
            self.display_font_value = str(self.config_data.get("display_font", "system") or "system")

            try:
                dialog.destroy()
            except Exception:
                pass

            try:
                self._apply_display_font()
            except Exception:
                pass
            try:
                self.file_tree.configure(height=int(self.config_data.get("file_list_height", 11)))
            except Exception:
                pass
            try:
                self._restart_hotkey_listener()
            except Exception:
                pass
            try:
                _apply_autostart(self)
            except Exception:
                pass
            try:
                _restart_old_watch(self)
            except Exception:
                pass
            try:
                rebuild_runtime()
            except Exception:
                pass
            try:
                self.set_status("\u8bbe\u7f6e\u5df2\u4fdd\u5b58")
            except Exception:
                pass
            try:
                self.refresh_orders()
            except Exception:
                pass
        except Exception as exc:
            dialog._cardproof_saving = False
            mod.messagebox.showerror("\u4fdd\u5b58\u5931\u8d25", str(exc))
            return

    save_button = ttk.Button(buttons, text="\u4fdd\u5b58", command=save_settings)
    save_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
    dialog.bind("<Control-s>", lambda _e: save_settings())

    try:
        buttons.grid_remove()
    except Exception:
        pass

    footer = ttk.Frame(outer, padding=(0, 10, 0, 0))
    footer.grid(row=1, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    ttk.Button(footer, text="\u53d6\u6d88", command=dialog.destroy).grid(row=0, column=1, sticky="e")
    footer_save_button = ttk.Button(footer, text="\u4fdd\u5b58", command=save_settings)
    footer_save_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
    footer_save_button.bind("<ButtonRelease-1>", lambda _e: (save_settings(), "break"))
    dialog.protocol("WM_DELETE_WINDOW", save_settings)

    def clear_dialog_ref(_event=None):
        if getattr(self, "_cardproof_settings_dialog", None) is dialog:
            self._cardproof_settings_dialog = None

    dialog.bind("<Destroy>", clear_dialog_ref)
    try:
        api_provider_var.trace_add("write", sync_api_provider)
        source_mode_var.trace_add("write", sync_source_mode)
        range_mode_var.trace_add("write", sync_range_mode)
    except Exception:
        pass

    sync_api_provider()
    sync_source_mode()
    sync_range_mode()
    sync_model_placeholder()
    sync_scrollregion()
    dialog.after(30, sync_scrollregion)


def _start_old_watch(self) -> None:
    if not bool(self.config_data.get("old_watch_enabled", DEFAULT_CONFIG.get("old_watch_enabled", True))):
        return
    if not _source_is_local(self):
        return
    thread = getattr(self, "_old_watch_thread", None)
    if thread and thread.is_alive():
        return
    self._old_watch_stop = threading.Event()
    self._old_watch_state = {}
    self._old_watch_thread = threading.Thread(
        target=_old_watch_loop,
        args=(self,),
        name="CardProofOldWatch",
        daemon=True,
    )
    self._old_watch_thread.start()


def _stop_old_watch(self) -> None:
    stop_event = getattr(self, "_old_watch_stop", None)
    if stop_event is not None:
        stop_event.set()
    self._old_watch_stop = None


def _restart_old_watch(self) -> None:
    _stop_old_watch(self)
    _start_old_watch(self)


def _reorder_face_buttons(self) -> None:
    buttons = getattr(self, "proofread_face_mode_buttons", None) or {}
    order = [("front", 0), ("back", 1), ("all", 2)]
    for key, column in order:
        button = buttons.get(key)
        if button is None:
            continue
        try:
            button.grid_configure(column=column, padx=(0 if column == 0 else 6, 0))
        except Exception:
            continue


def _prefix_report(scope: str, report: dict) -> dict:
    scope_text = str(scope or "").strip() or "\u6b63\u9762"
    result = {
        "summary": f"{scope_text}: {str(report.get('summary', '') or '').strip()}",
        "recognized_text": [f"[{scope_text}] {text}" for text in (report.get("recognized_text") or [])],
        "must_fix": [],
        "confirm": [],
        "looks_ok": [f"[{scope_text}] {text}" for text in (report.get("looks_ok") or [])],
        "missing_or_changed_elements": [],
        "prepress_risks": [],
    }
    for key in ("must_fix", "confirm", "missing_or_changed_elements", "prepress_risks"):
        for item in (report.get(key) or []):
            if isinstance(item, dict):
                patched = dict(item)
                patched["title"] = f"[{scope_text}] {patched.get('title', '')}".strip()
                result[key].append(patched)
    return result


def _merge_reports(*reports: dict) -> dict:
    summaries = [str(report.get("summary", "") or "").strip() for report in reports if report]
    merged = {
        "summary": " ; ".join([text for text in summaries if text]) or "\u6682\u65e0",
        "recognized_text": [],
        "must_fix": [],
        "confirm": [],
        "looks_ok": [],
        "missing_or_changed_elements": [],
        "prepress_risks": [],
    }
    for report in reports:
        if not report:
            continue
        for key in merged.keys():
            if key == "summary":
                continue
            merged[key].extend(report.get(key) or [])
    return merged


def _proofread_face_scope(self, source_items, mode: str, emit_intermediate: bool = False):
    mode = (mode or "front").strip().lower()
    root_hint = self._current_root_hint()
    if mode in {"front", "back"}:
        targets = _patched_latest_face_targets(self, source_items, mode)
        files = self._build_proofread_items(targets, include_old=True)
        return self._proofread_items(files, root_hint)

    front_targets = _patched_latest_face_targets(self, source_items, "front")
    back_targets = _patched_latest_face_targets(self, source_items, "back")
    front_report = None
    back_report = None
    front_files = self._build_proofread_items(front_targets, include_old=True) if front_targets else []
    back_files = self._build_proofread_items(back_targets, include_old=True) if back_targets else []

    def run_front():
        if not front_files:
            return {}
        return _prefix_report(FACE_FRONT, self._proofread_items(front_files, root_hint))

    def run_back():
        if not back_files:
            return {}
        return _prefix_report(FACE_BACK, self._proofread_items(back_files, root_hint))

    if front_files and back_files:
        with ThreadPoolExecutor(max_workers=2) as pool:
            front_future = pool.submit(run_front)
            back_future = pool.submit(run_back)
            front_report = front_future.result()
            if emit_intermediate and front_report:
                try:
                    self.after(0, lambda report=front_report: self._render_report(report))
                except Exception:
                    pass
            back_report = back_future.result()
    else:
        front_report = run_front()
        if emit_intermediate and front_report:
            try:
                self.after(0, lambda report=front_report: self._render_report(report))
            except Exception:
                pass
        back_report = run_back()
    return _merge_reports(front_report or {}, back_report or {})


def _patched_check_selected_order_v2(self):
    if not self.selected_order:
        mod.messagebox.showinfo("\u63d0\u793a", "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u8ba2\u5355")
        return
    mode = getattr(self, "proofread_face_mode_var", None).get() if hasattr(self, "proofread_face_mode_var") else "front"
    label = {"front": FACE_FRONT, "back": FACE_BACK, "all": "\u5168\u90e8"}.get(mode, FACE_FRONT)
    self.set_status(f"\u6b63\u5728\u68c0\u67e5\u8ba2\u5355: {self.selected_order.order_id} ({label})")

    def worker():
        source_items = self.selected_order.files
        return _proofread_face_scope(self, source_items, mode, emit_intermediate=(mode == "all"))

    self._run_bg(worker, self.on_report, self.on_error)


def _patched_check_latest_print_standard_v2(self):
    if not self.selected_order and not self.manual_files:
        mod.messagebox.showinfo("\u63d0\u793a", "\u8bf7\u5148\u9009\u62e9\u4e00\u4e2a\u8ba2\u5355")
        return
    if self._auto_check_running:
        self.set_status("\u6b63\u5728\u68c0\u6d4b, \u8bf7\u7a0d\u5019")
        return
    source_items = self.manual_files or (self.selected_order.files if self.selected_order else [])
    if not source_items:
        mod.messagebox.showinfo("\u63d0\u793a", "\u5f53\u524d\u6ca1\u6709\u53ef\u68c0\u6d4b\u7684\u6587\u4ef6")
        return
    mode = getattr(self, "proofread_face_mode_var", None).get() if hasattr(self, "proofread_face_mode_var") else "front"
    label = {"front": FACE_FRONT, "back": FACE_BACK, "all": "\u5168\u90e8"}.get(mode, FACE_FRONT)
    self.set_status(f"\u6b63\u5728\u68c0\u6d4b\u6700\u65b0\u6587\u4ef6: {label}")

    def worker():
        return _proofread_face_scope(self, source_items, mode, emit_intermediate=(mode == "all"))

    self._run_bg(worker, self.on_report, self.on_error)


def _patched_init_v2(self, *args, **kwargs):
    _orig_proofapp_init(self, *args, **kwargs)
    try:
        self.config_data = _ensure_runtime_config_file(self.config_data)
    except Exception:
        pass
    self.proofread_face_mode_var.set("front")
    _reorder_face_buttons(self)
    self._old_watch_state = {}
    self._old_watch_stop = None
    self._old_watch_thread = None
    _apply_autostart(self)
    _start_old_watch(self)
    try:
        _old_watch_maintain_once(self)
    except Exception:
        pass
    stored_config = _read_runtime_config()
    self._needs_initial_setup = (not stored_config) or not str(self.config_data.get("openai_base_url", "") or "").strip() or not str(self.config_data.get("openai_model", "") or "").strip()
    if self._needs_initial_setup:
        try:
            self.after(120, lambda: _open_initial_setup(self))
        except Exception:
            pass


def _patched_on_close_v2(self):
    _stop_old_watch(self)
    _orig_proofapp_close(self)


def _open_initial_setup(self):
    try:
        existing = getattr(self, "_cardproof_initial_setup_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        config = _normalize_loaded_config(self.config_data)
        dialog = tk.Toplevel(self)
        dialog.title("\u9996\u6b21\u914d\u7f6e")
        dialog.geometry("620x340")
        dialog.minsize(560, 300)
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        self._cardproof_initial_setup_dialog = dialog

        frame = ttk.Frame(dialog, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        provider_map = {value: key for key, value in API_PROVIDER_LABELS.items()}
        api_provider_var = tk.StringVar(value=API_PROVIDER_LABELS.get(_normalize_api_provider(config.get("openai_provider")), API_PROVIDER_LABELS["builtin"]))
        api_base_url_var = tk.StringVar(value=str(config.get("openai_custom_base_url") or config.get("openai_base_url") or _resolve_api_base_url(config.get("openai_provider"))))
        api_key_var = tk.StringVar(value=str(config.get("openai_api_key", "") or ""))
        model_var = tk.StringVar(value=str(config.get("openai_model", "") or _resolve_default_model(config.get("openai_provider")) or ""))
        source_mode_var = tk.StringVar(value="\u672c\u5730\u76ee\u5f55" if str(config.get("source_mode", "local")).lower() == "local" else "WebDAV")
        local_root_var = tk.StringVar(value=str(config.get("local_root", "") or ""))
        dav_url_var = tk.StringVar(value=str(config.get("dav_url", "") or ""))

        ttk.Label(frame, text="\u8bf7\u5148\u5b8c\u6210\u57fa\u672c\u914d\u7f6e", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        def add_row(row, label, widget):
            ttk.Label(frame, text=label, width=12).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=(0, 8))
            widget.grid(row=row, column=1, sticky="ew", pady=(0, 8))

        source_box = ttk.Combobox(frame, textvariable=source_mode_var, values=("\u672c\u5730\u76ee\u5f55", "WebDAV"), state="readonly")
        add_row(1, "\u6587\u4ef6\u6765\u6e90", source_box)

        source_stack = ttk.Frame(frame)
        source_stack.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        source_stack.columnconfigure(1, weight=1)

        local_row = ttk.Frame(source_stack)
        local_row.columnconfigure(1, weight=1)
        ttk.Label(local_row, text="\u672c\u5730\u76ee\u5f55", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(local_row, textvariable=local_root_var).grid(row=0, column=1, sticky="ew")

        webdav_row = ttk.Frame(source_stack)
        webdav_row.columnconfigure(1, weight=1)
        ttk.Label(webdav_row, text="WebDAV URL", width=12).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(webdav_row, textvariable=dav_url_var).grid(row=0, column=1, sticky="ew")

        ttk.Button(
            local_row,
            text="\u9009\u62e9",
            command=lambda: (
                lambda picked=mod.filedialog.askdirectory(initialdir=str(Path(local_root_var.get() or APP_DIR).parent if str(local_root_var.get() or "").strip() else APP_DIR)):
                    local_root_var.set(picked or local_root_var.get())
            )(),
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        api_provider_box = ttk.Combobox(frame, textvariable=api_provider_var, values=tuple(API_PROVIDER_LABELS.values()), state="readonly")
        add_row(3, "API \u6765\u6e90", api_provider_box)
        add_row(4, "API Base URL", ttk.Entry(frame, textvariable=api_base_url_var))
        add_row(5, "API Key", ttk.Entry(frame, textvariable=api_key_var, show="*"))
        model_row = ttk.Frame(frame)
        model_row.columnconfigure(0, weight=1)
        ttk.Entry(model_row, textvariable=model_var).grid(row=0, column=0, sticky="ew")
        initial_model_status_var = tk.StringVar(value="")
        def fetch_initial_models():
            provider_key = provider_map.get(api_provider_var.get(), "builtin")
            base_url = _resolve_api_base_url(provider_key, api_base_url_var.get())
            api_key = str(api_key_var.get() or "").strip()
            if not base_url:
                mod.messagebox.showwarning("\u63d0\u793a", "\u8bf7\u5148\u586b\u5199 API Base URL")
                return
            initial_fetch_button.configure(state="disabled")
            initial_model_status_var.set("\u6b63\u5728\u83b7\u53d6\u6a21\u578b...")
            def worker():
                return _fetch_remote_models(base_url, api_key, "dual")
            def on_success(values):
                initial_fetch_button.configure(state="normal")
                if values:
                    model_var.set(values[0])
                    initial_model_status_var.set(f"\u5df2\u83b7\u53d6 {len(values)} \u4e2a\u6a21\u578b")
                else:
                    initial_model_status_var.set("\u672a\u8fd4\u56de\u6a21\u578b")
            def on_failure(exc):
                initial_fetch_button.configure(state="normal")
                initial_model_status_var.set("\u83b7\u53d6\u5931\u8d25")
                mod.messagebox.showerror("\u83b7\u53d6\u6a21\u578b\u5931\u8d25", str(exc))
            self._run_bg(worker, on_success, on_failure)
        initial_fetch_button = ttk.Button(model_row, text="\u5237\u65b0\u6a21\u578b", command=fetch_initial_models)
        initial_fetch_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Label(model_row, textvariable=initial_model_status_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        add_row(6, "\u6a21\u578b", model_row)

        footer = ttk.Frame(frame)
        footer.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)

        def sync_source_rows(*_):
            local_row.grid_forget()
            webdav_row.grid_forget()
            if source_mode_var.get() == "WebDAV":
                webdav_row.grid(row=0, column=0, sticky="ew")
            else:
                local_row.grid(row=0, column=0, sticky="ew")

        def sync_api_provider(*_):
            provider_key = provider_map.get(api_provider_var.get(), "builtin")
            if provider_key != "custom":
                api_base_url_var.set(_resolve_api_base_url(provider_key, api_base_url_var.get()))
            if not str(model_var.get() or "").strip():
                model_var.set(_resolve_default_model(provider_key))

        def save_initial():
            provider_key = provider_map.get(api_provider_var.get(), "builtin")
            source_key = "webdav" if source_mode_var.get() == "WebDAV" else "local"
            next_config = dict(self.config_data)
            next_config.update({
                "source_mode": source_key,
                "local_root": str(local_root_var.get() or "").strip(),
                "dav_url": str(dav_url_var.get() or "").strip(),
                "openai_provider": provider_key,
                "openai_custom_base_url": str(api_base_url_var.get() or "").strip() if provider_key == "custom" else "",
                "openai_base_url": _resolve_api_base_url(provider_key, api_base_url_var.get()),
                "openai_api_key": str(api_key_var.get() or "").strip(),
                "openai_model": str(model_var.get() or "").strip() or _resolve_default_model(provider_key),
            })
            if source_key == "local":
                next_config["cache_dir"] = _default_local_cache_dir(next_config.get("local_root"))
            next_config = _normalize_loaded_config(next_config)
            mod.save_config(next_config)
            self.config_data = next_config
            try:
                self._cardproof_initial_setup_dialog = None
            except Exception:
                pass
            try:
                dialog.destroy()
            except Exception:
                pass
            try:
                self.set_status("\u9996\u6b21\u914d\u7f6e\u5df2\u4fdd\u5b58")
            except Exception:
                pass
            try:
                self.source = mod.WebDavClient(
                    str(self.config_data.get("dav_url", "") or "").strip(),
                    str(self.config_data.get("dav_user", "") or "").strip(),
                    str(self.config_data.get("dav_pass", "") or "").strip(),
                    str(self.config_data.get("cache_dir", "") or "").strip() or None,
                ) if source_key == "webdav" else mod.LocalFolderClient(str(self.config_data.get("local_root", "") or APP_DIR))
                self.openai = mod.OpenAIClient(
                    str(self.config_data.get("openai_base_url", "") or "").strip(),
                    str(self.config_data.get("openai_api_key", "") or "").strip(),
                    str(self.config_data.get("openai_model", "") or "").strip(),
                    str(self.config_data.get("api_mode", "auto") or "auto").strip(),
                    str(self.config_data.get("api_auth_style", "dual") or "dual").strip(),
                    str(self.config_data.get("proofread_prompt", "") or ""),
                    str(self.config_data.get("custom_prompt", "") or ""),
                )
            except Exception:
                pass
            try:
                self.refresh_orders()
            except Exception:
                pass

        ttk.Button(footer, text="\u4fdd\u5b58", command=save_initial).grid(row=0, column=1, sticky="e")
        try:
            source_mode_var.trace_add("write", sync_source_rows)
            api_provider_var.trace_add("write", sync_api_provider)
        except Exception:
            pass
        sync_source_rows()
        sync_api_provider()
        self.set_status("\u8bf7\u5148\u5b8c\u6210 API \u548c\u6587\u4ef6\u6765\u6e90\u914d\u7f6e")
    except Exception:
        pass


mod.ProofApp.__init__ = _patched_init_v2
mod.ProofApp._on_close = _patched_on_close_v2
mod.ProofApp.open_settings = _patched_open_settings_v4
mod.ProofApp.check_selected_order = _patched_check_selected_order_v2
mod.ProofApp.check_latest_print_standard = _patched_check_latest_print_standard_v2


def main():
    if "--self-test" in sys.argv:
        mod.self_test()
        return
    app = mod.ProofApp()
    app.mainloop()


if __name__ == "__main__":
    main()
