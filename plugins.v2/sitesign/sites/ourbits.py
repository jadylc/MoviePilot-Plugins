# -*- coding: utf-8 -*-
"""签到-我堡(ourbits)站点

我堡 attendance.php 页面内嵌 Cloudflare Turnstile 交互验证：
页面加载后会渲染一个 cf-turnstile 小框，过完人机验证后
TurnstileCallback 自动 $('form#attendance').submit() 完成签到。

所以签到必须由一个真实浏览器会话加载 attendance.php、过 Turnstile、
并被页内 JS 自动 submit，一个会话内闭环完成。纯 HTTP/GET 拿不到
Turnstile 现场签发的 token，也无法离线缓存。

本模块在检测到 attendance 页面仍处于待验证状态时，交给 FlareSolverr
(nodriver 版更佳) 以浏览器渲染整页、过验证、自动提交，拿回签到后的
页面再判定结果。注意 FlareSolverr 起的是全新浏览器会话，必须把站点
登录 Cookie 一并注入，否则会以游客身份访问 attendance.php 而拿不到
签到表单。
"""
import re
from typing import List, Tuple
from urllib.parse import urljoin, urlparse

from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.log import logger
from app.plugins.sitesign.sites import _ISiteSigninHandler
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class OurBits(_ISiteSigninHandler):
    """
    我堡签到
    """
    # 匹配的站点Url
    site_url = "ourbits.club"

    # 签到成功/已签到 关键字（页面命中即视为签到完成）
    _succeed_regex = ['已签到', '签到成功', '签到已得', '连续签到']

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_url = site_info.get("url")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout") or 60
        flaresolverr_url = site_info.get("flaresolverr_url")

        if not site_url or not site_cookie:
            logger.warn(f"未配置 {site} 的站点地址或Cookie，无法签到")
            return False, ""

        # 拼接签到地址
        if str(site_url).find("attendance.php") == -1:
            checkin_url = urljoin(site_url, "attendance.php")
        else:
            checkin_url = site_url

        proxies = settings.PROXY if proxy else None
        # 先用普通方式访问签到页，看是否已签到 / 是否存在 Turnstile 待过
        res = RequestUtils(cookies=site_cookie,
                           ua=ua,
                           proxies=proxies,
                           timeout=timeout
                           ).get_res(url=checkin_url)
        html_text = self._decode(res)

        # 已签到
        if self.sign_in_result(html_res=html_text, regexs=self._succeed_regex):
            logger.info(f"{site} 今日已签到")
            return True, "今日已签到"

        # Cookie 失效
        if html_text and "login.php" in html_text:
            logger.warn(f"{site} Cookie已失效")
            return False, "签到失败，Cookie已失效"

        # 没签到成功：判定是否为 Turnstile 待过页
        need_turnstile = self._has_turnstile(html_text)
        has_form = ('form id="attendance"' in html_text) or ('form#attendance' in html_text)
        logger.info(f"{site} 签到页诊断：len={len(html_text)} "
                    f"含turnstile={need_turnstile} 含attendance_form={has_form}")

        if not need_turnstile:
            # 不是已签到、也不是 Turnstile 待过页 → 状态不明，如实报告
            logger.warn(f"{site} 进入签到页但未识别签到状态，无法确认是否签到成功")
            return False, "进入签到页但未确认签到结果"

        # 需要 Turnstile：交给 FlareSolverr 以浏览器整页渲染、过验证、自动提交
        if not flaresolverr_url:
            logger.warn(f"{site} 需要Cloudflare Turnstile验证，但未配置FlareSolverr地址")
            return False, "签到失败，需Cloudflare Turnstile验证，未配置FlareSolverr"

        return self._flaresolverr_signin(site=site,
                                         url=checkin_url,
                                         flaresolverr_url=flaresolverr_url,
                                         site_cookie=site_cookie,
                                         timeout=timeout)

    @staticmethod
    def _decode(res) -> str:
        """
        用 chardet 解码响应，避免中文站点因响应头缺 charset 导致乱码、关键字匹配失败
        """
        if not res:
            return ""
        raw = res.content
        if not raw:
            return res.text or ""
        try:
            import chardet
            encoding = chardet.detect(raw).get("encoding")
            if encoding:
                return raw.decode(encoding, errors="replace")
        except Exception as e:
            logger.error(f"chardet解码失败：{str(e)}")
        return res.text or ""

    def _hit_succeed(self, text: str) -> bool:
        """
        判定文本是否命中签到成功关键字（复用 _succeed_regex 单一来源）
        """
        if not text:
            return False
        return any(re.search(kw, text, re.IGNORECASE) for kw in self._succeed_regex)

    @staticmethod
    def _has_turnstile(html: str) -> bool:
        """
        判定页面是否存在待处理的 Cloudflare Turnstile（attendance form 未提交）
        """
        if not html:
            return False
        low = html.lower()
        if "cf-turnstile" not in low:
            return False
        # Turnstile 容器在、且 attendance form 还在（未提交状态）
        return ("form" in low and "attendance" in low) or "cf-turnstile-response" in low

    @staticmethod
    def _cookie_to_list(site_cookie: str, url: str) -> List[dict]:
        """
        把 "k=v; k2=v2" 形式的站点 Cookie 转成 FlareSolverr 需要的 cookies 数组，
        并附上目标域名，供其在新浏览器会话中带上登录态访问
        """
        domain = urlparse(url).hostname or ""
        cookies = []
        for part in str(site_cookie or "").split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": domain,
            })
        return cookies

    def _flaresolverr_signin(self, site: str, url: str, flaresolverr_url: str,
                             site_cookie: str, timeout: int) -> Tuple[bool, str]:
        """
        通过 FlareSolverr 加载 attendance.php：
        - 注入站点登录 Cookie，保证以已登录身份访问，才能拿到签到用的 Turnstile 表单
        - nodriver 内部渲染 Turnstile、过验证、TurnstileCallback 自动 submit form
        - 等待流程完成后拿回签到后的页面，判定是否成功
        """
        fs = str(flaresolverr_url).rstrip("/")
        # FlareSolverr 需要足够时长等 Turnstile 加载 + 过验证 + 自动 submit
        max_timeout = int((timeout or 60) * 1000)
        body = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout,
            "cookies": self._cookie_to_list(site_cookie, url),
        }
        try:
            res = RequestUtils(content_type="application/json",
                               timeout=(timeout or 60) + 60
                               ).post_res(url=f"{fs}/v1", json=body)
            if not res:
                logger.warn(f"{site} FlareSolverr 无响应：{fs}")
                return False, "FlareSolverr 无响应"
            if res.status_code != 200:
                logger.warn(f"{site} FlareSolverr 调用失败，状态码：{res.status_code}")
                return False, f"FlareSolverr 调用失败，状态码：{res.status_code}"
            data = res.json()
            if data.get("status") != "ok":
                logger.warn(f"{site} FlareSolverr 未成功：{data.get('message')}")
                return False, f"FlareSolverr 过盾未成功：{data.get('message')}"
            solution = data.get("solution") or {}
            page = solution.get("response") or ""
            sol_url = solution.get("url")
            sol_status = solution.get("status")
            still_turnstile = "cf-turnstile" in page.lower()
            logger.info(f"{site} FlareSolverr 返回：status={sol_status} url={sol_url} "
                        f"len={len(page)} 仍含turnstile={still_turnstile}")
            logger.info(f"{site} FlareSolverr 过盾后页面前500字：{page[:500]}")
            if not page:
                return False, "FlareSolverr 过盾后页面为空"
            # Cookie 失效：被打回登录页
            if "login.php" in page:
                logger.warn(f"{site} FlareSolverr 访问被打回登录页，Cookie可能已失效")
                return False, "FlareSolverr 过盾后被打回登录页，Cookie已失效"
            # 命中签到成功关键字（优先级最高）
            if self._hit_succeed(page):
                logger.info(f"{site} FlareSolverr 过盾签到成功")
                return True, "FlareSolverr 过盾签到成功"
            # 仍存在 Turnstile 待过 → 验证没过、form 没 submit
            if still_turnstile and "attendance" in page.lower():
                logger.warn(f"{site} FlareSolverr 过盾后 Turnstile 仍在，签到可能未完成")
                return False, "FlareSolverr 过盾后签到可能未完成（Turnstile仍在）"
            # 页面已无 Turnstile 但也没签到关键字 → 进入签到页但未确认
            logger.warn(f"{site} FlareSolverr 过盾成功但未匹配到签到成功标志")
            return False, "FlareSolverr 过盾成功但未确认签到结果"
        except Exception as e:
            logger.warn(f"{site} FlareSolverr 调用异常：{str(e)}")
            return False, f"FlareSolverr 调用异常：{str(e)}"
