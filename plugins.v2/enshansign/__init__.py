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
    plugin_version = "1.0.0"
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
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
                  "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }

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

    def _build_session(self, cookie: str) -> requests.Session:
        session = requests.Session()
        session.headers.update(self._headers)
        session.headers["Cookie"] = cookie
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

    def _daily_login(self, session: requests.Session) -> Tuple[bool, str, Optional[str]]:
        traces = []
        formhash = None
        uid = None
        for login_url in self._login_urls:
            try:
                response = session.get(login_url, timeout=20)
                traces.append(f"{login_url} -> {response.status_code}")
                logger.info(f"[enshan] 登录探测: {login_url} status={response.status_code}")
                if response.status_code == 200:
                    formhash, uid = self._extract_auth_params(response.text)
                    if formhash and uid:
                        return True, "登录成功", formhash
                elif response.status_code in (520, 521, 522, 523, 524):
                    time.sleep(random.uniform(1.3, 2.6))
            except requests.RequestException as err:
                traces.append(f"{login_url} -> error: {err}")
                time.sleep(random.uniform(1.0, 2.0))
        return False, f"登录失败: {'; '.join(traces)}", None

    def _perform_checkin(self, session: requests.Session, cookie: str, formhash: str) -> Tuple[bool, str]:
        url = f"{self._base_url}/plugin.php?id=erling_qd%3Aaction&action=sign"
        headers = {
            "User-Agent": self._headers["User-Agent"],
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.right.com.cn",
            "Connection": "keep-alive",
            "Referer": "https://www.right.com.cn/forum/erling_qd-sign_in.html",
            "Cookie": cookie,
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        }
        response = session.post(url, headers=headers, data=f"formhash={formhash}", timeout=20)
        if response.status_code != 200:
            return False, f"签到请求失败，状态码: {response.status_code}"
        try:
            data = response.json() if response.text else {}
        except Exception:
            return False, "签到响应不是 JSON"

        message = str(data.get("message", "")).strip()
        if data.get("success") is True:
            return True, message or "签到成功"
        if "成功" in message or "已签到" in message or "已经签到" in message:
            return True, message or "今日已签到"
        return False, message or "签到失败"

    def _run_one(self, cookie: str, index: int) -> Tuple[bool, str]:
        session = self._build_session(cookie)
        ok, login_msg, formhash = self._daily_login(session)
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
