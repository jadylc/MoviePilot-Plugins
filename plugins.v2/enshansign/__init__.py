from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import random
import re
import threading
import time

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType


class EnshanSign(_PluginBase):
    plugin_name = "恩山论坛签到"
    plugin_desc = "使用 Cookie 执行恩山论坛自动签到（支持多账号）"
    plugin_icon = "Adguard_A.png"
    plugin_version = "1.0.1"
    plugin_author = "Jadylc"
    author_url = "https://github.com/jadylc"
    plugin_config_prefix = "enshansign_"
    plugin_order = 1
    auth_level = 2

    _enabled: bool = False
    _onlyonce: bool = False
    _notify: bool = True
    _cron: Optional[str] = "5 2 * * *"
    _cookie_text: str = ""
    _scheduler: Optional[BackgroundScheduler] = None
    _event = threading.Event()

    _base_url = "https://www.right.com.cn/forum"
    _credit_url = f"{_base_url}/home.php?mod=spacecp&ac=credit&showcredit=1"
    _login_urls = [
        f"{_base_url}/forum.php",
        f"{_base_url}/",
        _credit_url,
        f"{_base_url}/home.php?mod=space",
    ]
    _headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
                  "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    _cf_status_codes = (520, 521, 522, 523, 524)

    def init_plugin(self, config: dict = None):
        self.stop_service()
        if config:
            self._enabled = bool(config.get("enshansign_enabled", False))
            self._onlyonce = bool(config.get("enshansign_onlyonce", False))
            self._notify = bool(config.get("enshansign_notify", True))
            self._cron = config.get("enshansign_cron") or "5 2 * * *"
            self._cookie_text = config.get("enshansign_cookie") or ""

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self._run_sign_job,
                trigger="date",
                run_date=datetime.now(pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="恩山论坛签到"
            )
            self._onlyonce = False
            self.update_config({
                "enshansign_enabled": self._enabled,
                "enshansign_onlyonce": self._onlyonce,
                "enshansign_notify": self._notify,
                "enshansign_cron": self._cron,
                "enshansign_cookie": self._cookie_text,
            })
            if self._scheduler and self._scheduler.get_jobs():
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            return [{
                "id": "enshansign",
                "name": "恩山论坛签到",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self._run_sign_job,
                "kwargs": {},
            }]
        except Exception as err:
            logger.error(f"恩山签到定时任务配置错误: {err}")
            return []

    @staticmethod
    def _parse_cookies(cookie_str: str) -> List[str]:
        if not cookie_str:
            return []
        items: List[str] = []
        for line in cookie_str.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            for part in line.split("&&"):
                part = part.strip()
                if part and part not in items:
                    items.append(part)
        return items

    @staticmethod
    def _cookie_to_dict(cookie: str) -> Dict[str, str]:
        cookie_map: Dict[str, str] = {}
        if not cookie:
            return cookie_map
        for item in cookie.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                cookie_map[key] = value
        return cookie_map

    def _apply_cookie(self, session: requests.Session, cookie: str):
        cookie_map = self._cookie_to_dict(cookie)
        if not cookie_map:
            return
        session.headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in cookie_map.items()])
        for domain in ("www.right.com.cn", ".right.com.cn", "right.com.cn"):
            for key, value in cookie_map.items():
                session.cookies.set(key, value, domain=domain, path="/")

    @staticmethod
    def _cookie_has_clearance(cookie: str) -> bool:
        cookie_map = EnshanSign._cookie_to_dict(cookie)
        return bool(cookie_map.get("cf_clearance") or cookie_map.get("__cf_bm"))

    @staticmethod
    def _cookie_debug_summary(cookie: str) -> str:
        cookie_map = EnshanSign._cookie_to_dict(cookie)
        keys = [
            "rHEX_2132_auth",
            "rHEX_2132_saltkey",
            "rHEX_2132_sid",
            "rHEX_2132_lastact",
            "https_waf_cookie",
            "https_ydclearance",
            "cf_clearance",
            "__cf_bm",
        ]
        parts = []
        for key in keys:
            value = cookie_map.get(key)
            if value:
                parts.append(f"{key}=present(len={len(value)})")
            else:
                parts.append(f"{key}=missing")
        return ", ".join(parts)

    @staticmethod
    def _response_debug_summary(response: requests.Response) -> str:
        server = response.headers.get("Server", "-")
        location = response.headers.get("Location", "-")
        x_cache = response.headers.get("X-Cache", "-")
        x_request_id = response.headers.get("X-Request-Id", "-")
        cookie_keys = ",".join(response.cookies.keys()) if response.cookies else "-"
        return (
            f"server={server}, location={location}, x-cache={x_cache}, "
            f"x-request-id={x_request_id}, set-cookie-keys={cookie_keys}"
        )

    @staticmethod
    def _response_body_preview(response: requests.Response, limit: int = 160) -> str:
        text = (response.text or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        return text[:limit]

    def _build_session(self, cookie: str) -> requests.Session:
        session = requests.Session()
        session.headers.update(self._headers)
        session.headers["Referer"] = f"{self._base_url}/forum.php"
        session.headers["Origin"] = "https://www.right.com.cn"
        self._apply_cookie(session, cookie)
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.2,
            status_forcelist=[429, 500, 502, 503, 504, 520, 521, 522, 523, 524],
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _extract_uid_from_cookie(self, cookie: str) -> Optional[str]:
        cookie_map = self._cookie_to_dict(cookie)
        for key, value in cookie_map.items():
            if key.endswith("_uid") and value.isdigit():
                return value
        return None

    @staticmethod
    def _extract_auth_params(page_text: str) -> Tuple[Optional[str], Optional[str]]:
        formhash_patterns = [
            r'name="formhash"\s+value="([^"]+)"',
            r'formhash=([0-9a-fA-F]{8,})',
            r'"formhash"\s*:\s*"([^"]+)"',
        ]
        uid_patterns = [
            r"discuz_uid\s*=\s*'(\d+)'",
            r"uid=(\d+)",
            r'"uid"\s*:\s*"(\d+)"',
        ]
        formhash = None
        uid = None
        for pattern in formhash_patterns:
            match = re.search(pattern, page_text)
            if match:
                formhash = match.group(1).strip()
                break
        for pattern in uid_patterns:
            match = re.search(pattern, page_text)
            if match:
                uid = match.group(1).strip()
                break
        return formhash, uid

    def _daily_login(self, session: requests.Session, cookie: str) -> Tuple[bool, str, Optional[str]]:
        traces = []
        formhash = None
        uid = self._extract_uid_from_cookie(cookie)
        logger.info(f"[enshan] login cookie state: {self._cookie_debug_summary(cookie)}")
        login_urls = [
            f"{self._base_url}/plugin.php?id=erling_qd:sign",
            *self._login_urls,
            f"{self._base_url}/plugin.php?id=erling_qd%3Asign",
        ]
        for login_url in login_urls:
            try:
                response = session.get(login_url, timeout=20)
                traces.append(f"{login_url} -> {response.status_code}")
                logger.info(f"[enshan] login probe: {login_url} status={response.status_code}")
                logger.info(f"[enshan] login probe response: {self._response_debug_summary(response)}")
                if response.status_code == 200:
                    page_formhash, page_uid = self._extract_auth_params(response.text)
                    formhash = page_formhash or formhash
                    uid = page_uid or uid
                    if formhash and uid:
                        return True, "login ok", formhash
                    if formhash:
                        return True, "login ok (formhash)", formhash
                    logger.warning(
                        f"[enshan] login 200 but auth params missing: "
                        f"{self._response_debug_summary(response)} body={self._response_body_preview(response)}"
                    )
                elif response.status_code in self._cf_status_codes:
                    logger.warning(
                        f"[enshan] login probe got 52x: "
                        f"{self._response_debug_summary(response)} body={self._response_body_preview(response)}"
                    )
                    time.sleep(random.uniform(1.3, 2.6))
            except requests.RequestException as err:
                traces.append(f"{login_url} -> error: {err}")
                logger.warning(f"[enshan] login probe request error: {login_url} error={err}")
                time.sleep(random.uniform(1.0, 2.0))

        hint = ""
        trace_text = "; ".join(traces)
        if any(f" -> {code}" in trace_text for code in self._cf_status_codes):
            if not self._cookie_has_clearance(cookie):
                hint = " (detected 52x and cookie may miss cf_clearance/__cf_bm)"
            else:
                hint = " (detected 52x from Cloudflare/proxy path)"
        return False, f"login failed: {trace_text}{hint}", None


    def _perform_checkin(self, session: requests.Session, cookie: str, formhash: str) -> Tuple[bool, str]:
        url = f"{self._base_url}/plugin.php?id=erling_qd:action&action=sign"
        headers = {
            "User-Agent": self._headers["User-Agent"],
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": self._headers["Accept-Language"],
            "Accept-Encoding": self._headers["Accept-Encoding"],
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.right.com.cn",
            "Connection": "keep-alive",
            "Referer": f"{self._base_url}/plugin.php?id=erling_qd:sign",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": self._headers["sec-ch-ua"],
            "sec-ch-ua-mobile": self._headers["sec-ch-ua-mobile"],
            "sec-ch-ua-platform": self._headers["sec-ch-ua-platform"],
        }
        response = session.post(url, headers=headers, data=f"formhash={formhash}", timeout=20)
        if response.status_code != 200:
            hint = ""
            if response.status_code in self._cf_status_codes:
                hint = " / 52x from edge, check cf_clearance cookie and container outbound path"
            logger.warning(
                f"[enshan] checkin response status={response.status_code}: "
                f"{self._response_debug_summary(response)} body={self._response_body_preview(response)}"
            )
            return False, f"checkin request failed, status: {response.status_code}{hint}"
        try:
            data = response.json() if response.text else {}
        except Exception:
            logger.warning(
                f"[enshan] checkin response not json: "
                f"{self._response_debug_summary(response)} body={self._response_body_preview(response)}"
            )
            return False, "checkin response is not JSON"

        message = str(data.get("message", "")).strip()
        if data.get("success") is True:
            return True, message or "checkin success"
        if "成功" in message or "已签到" in message or "已经签到" in message:
            return True, message or "already checked in"
        return False, message or "checkin failed"


    def _run_one(self, cookie: str, index: int) -> Tuple[bool, str]:
        session = self._build_session(cookie)
        ok, login_msg, formhash = self._daily_login(session, cookie)
        if not ok or not formhash:
            return False, f"账号{index}: {login_msg}"
        ok, checkin_msg = self._perform_checkin(session, cookie, formhash)
        return ok, f"账号{index}: {checkin_msg}"

    def _run_sign_job(self):
        if self._event.is_set():
            return
        cookies = self._parse_cookies(self._cookie_text)
        if not cookies:
            msg = "未配置 enshan_cookie（支持换行或&&分隔）"
            logger.error(f"[enshan] {msg}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="恩山论坛签到失败",
                    text=msg
                )
            return

        logger.info(f"[enshan] 开始签到，共 {len(cookies)} 个账号")
        success = 0
        lines: List[str] = []
        for idx, cookie in enumerate(cookies, start=1):
            if self._event.is_set():
                break
            try:
                ok, line = self._run_one(cookie, idx)
                success += 1 if ok else 0
                lines.append(("✅ " if ok else "❌ ") + line)
                if idx < len(cookies):
                    time.sleep(random.uniform(1.5, 4.0))
            except Exception as err:
                logger.error(f"[enshan] 账号{idx}执行异常: {err}")
                lines.append(f"❌ 账号{idx}: 执行异常: {err}")

        summary = (
            f"总计: {len(cookies)}\n"
            f"成功: {success}\n"
            f"失败: {len(cookies) - success}\n\n"
            + "\n".join(lines)
        )
        logger.info(f"[enshan] 签到完成: {success}/{len(cookies)}")
        self.save_data("last_result", {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary,
            "success": success,
            "total": len(cookies),
        })
        if self._notify:
            self.post_message(
                mtype=NotificationType.Plugin,
                title=f"恩山论坛签到 {'成功' if success == len(cookies) else '完成'}",
                text=summary
            )

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        form = [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enshansign_enabled", "label": "启用插件"}
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enshansign_onlyonce", "label": "立即执行一次"}
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "sm": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enshansign_notify", "label": "发送通知"}
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "enshansign_cron",
                                        "label": "Cron 表达式",
                                        "placeholder": "5 2 * * *"
                                    }
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextarea",
                                    "props": {
                                        "model": "enshansign_cookie",
                                        "label": "恩山 Cookie",
                                        "rows": 8,
                                        "placeholder": "支持多账号：每行一个，或使用 && 分隔"
                                    }
                                }]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VAlert",
                                    "props": {
                                        "type": "info",
                                        "variant": "tonal",
                                        "text": "若返回 521，多为运行节点网络问题而非 Cookie 失效。"
                                    }
                                }]
                            }
                        ]
                    }
                ]
            }
        ]
        model = {
            "enshansign_enabled": False,
            "enshansign_onlyonce": False,
            "enshansign_notify": True,
            "enshansign_cron": "5 2 * * *",
            "enshansign_cookie": "",
        }
        return form, model

    def get_page(self) -> List[dict]:
        last = self.get_data("last_result") or {}
        text = last.get("summary") or "暂无执行记录"
        when = last.get("time") or "-"
        return [{
            "component": "VRow",
            "content": [{
                "component": "VCol",
                "props": {"cols": 12},
                "content": [{
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "title": f"最后执行时间: {when}",
                        "text": text,
                    }
                }]
            }]
        }]

    def stop_service(self):
        try:
            self._event.set()
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as err:
            logger.error(f"停止恩山签到服务失败: {err}")
        finally:
            self._event.clear()
