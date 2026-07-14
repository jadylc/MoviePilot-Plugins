# -*- coding: utf-8 -*-
import re
import time
from abc import ABCMeta, abstractmethod
from typing import Tuple

import chardet
from ruamel.yaml import CommentedMap

from app.core.config import settings
from app.helper.browser import PlaywrightHelper
from app.log import logger
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class _ISiteSigninHandler(metaclass=ABCMeta):
    """
    实现站点签到的基类，所有站点签到类都需要继承此类，并实现match和signin方法
    实现类放置到sitesignin目录下将会自动加载
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = ""

    # 裸「连续签到」可能出现在规则说明中，只匹配明确的完成态文案。
    _turnstile_succeed_regex = [
        '今日已签到', '签到成功', '签到已得', '本次签到获得', '已连续签到'
    ]

    @abstractmethod
    def match(self, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        if StringUtils.url_equal(url, self.site_url):
            return True
        return False

    @abstractmethod
    def signin(self, site_info: CommentedMap) -> Tuple[bool, str]:
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: True|False,签到结果信息
        """
        pass

    @staticmethod
    def get_page_source(url: str, cookie: str, ua: str, proxy: bool, render: bool,
                        token: str = None, timeout: int = None) -> str:
        """
        获取页面源码
        :param url: Url地址
        :param cookie: Cookie
        :param ua: UA
        :param proxy: 是否使用代理
        :param render: 是否渲染
        :param token: JWT Token
        :param timeout: 请求超时时间，单位秒
        :return: 页面源码，错误信息
        """
        if render:
            return PlaywrightHelper().get_page_source(url=url,
                                                      cookies=cookie,
                                                      ua=ua,
                                                      proxies=settings.PROXY_SERVER if proxy else None,
                                                      timeout=timeout or 60)
        else:
            if token:
                headers = {
                    "Authorization": token,
                    "User-Agent": ua
                }
            else:
                headers = {
                    "User-Agent": ua,
                    "Cookie": cookie
                }
            res = RequestUtils(headers=headers,
                               proxies=settings.PROXY if proxy else None,
                               timeout=timeout or 20).get_res(url=url)
            if res is not None:
                # 使用chardet检测字符编码
                raw_data = res.content
                if raw_data:
                    try:
                        result = chardet.detect(raw_data)
                        encoding = result['encoding']
                        # 解码为字符串
                        return raw_data.decode(encoding)
                    except Exception as e:
                        logger.error(f"chardet解码失败：{str(e)}")
                        return res.text
                else:
                    return res.text
            return ""

    @staticmethod
    def sign_in_result(html_res: str, regexs: list) -> bool:
        """
        判断是否签到成功
        """
        html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_res))
        for regex in regexs:
            if re.search(str(regex), html_text):
                return True
        return False

    @staticmethod
    def has_embedded_turnstile(html: str) -> bool:
        """判断 attendance 业务表单是否仍在等待内嵌 Turnstile。"""
        if not html:
            return False
        low = html.lower()
        if "cf-turnstile" not in low:
            return False
        attendance_form = re.search(
            r'<form\b[^>]*(?:id|name)\s*=\s*["\']?attendance["\']?', low
        )
        return bool(attendance_form and (
            "cf-turnstile" in low or "cf-turnstile-response" in low
        ))

    @staticmethod
    def _is_login_page(html: str) -> bool:
        if not html:
            return False
        low = html.lower()
        return ("takelogin.php" in low
                or ("login.php" in low and "name=\"username\"" in low
                    and "name=\"password\"" in low))

    @classmethod
    def signin_embedded_turnstile(cls, site: str, url: str, cookie: str, ua: str,
                                  proxies, timeout: int) -> Tuple[bool, str]:
        """在同一个真实浏览器页面中完成内嵌 Turnstile 与签到表单提交。"""
        browser_timeout = max(int(timeout or 60), 60)

        def callback(page):
            return cls._drive_turnstile_page(page=page, site=site, timeout=browser_timeout)

        try:
            result = PlaywrightHelper().action(url=url,
                                               callback=callback,
                                               cookies=cookie,
                                               ua=ua,
                                               proxies=proxies,
                                               headless=False,
                                               timeout=browser_timeout)
        except Exception as e:
            logger.warn(f"{site} 内嵌 Turnstile 浏览器仿真异常：{str(e)}")
            return False, f"浏览器仿真异常：{str(e)}"
        if (isinstance(result, tuple) and len(result) == 2
                and isinstance(result[0], bool)):
            return result
        logger.warn(f"{site} 浏览器仿真未返回内嵌 Turnstile 签到结果")
        return False, "浏览器仿真未完成内嵌 Turnstile 签到"

    @classmethod
    def _drive_turnstile_page(cls, page, site: str, timeout: int) -> Tuple[bool, str]:
        deadline = time.monotonic() + max(int(timeout or 60), 30)
        clicked = False
        submitted = False
        last_html = ""

        while time.monotonic() < deadline:
            try:
                last_html = page.content() or ""
            except Exception:
                cls._wait_browser_page(page, 1)
                continue

            pending = cls.has_embedded_turnstile(last_html)
            if not pending and cls.sign_in_result(last_html, cls._turnstile_succeed_regex):
                logger.info(f"{site} 内嵌 Turnstile 签到成功")
                return True, "签到成功"
            if not pending and cls._is_login_page(last_html):
                return False, "浏览器仿真后被打回登录页，Cookie已失效"

            if pending:
                if not clicked and cls._click_turnstile(page):
                    clicked = True
                if (not submitted and cls._submit_attendance_with_token(page)):
                    submitted = True

            cls._wait_browser_page(page, 1)

        pending = cls.has_embedded_turnstile(last_html)
        logger.warn(f"{site} 内嵌 Turnstile 签到超时："
                    f"仍待验证={pending} 已点击={clicked} 已提交={submitted}")
        if pending:
            return False, "浏览器仿真超时，内嵌 Turnstile 仍未通过"
        return False, "浏览器仿真完成但未确认签到结果"

    @staticmethod
    def _click_turnstile(page) -> bool:
        """点击 Cloudflare iframe 内可见的验证控件；托管模式则等待自动完成。"""
        try:
            frames = getattr(page, "frames", []) or []
            for frame in frames:
                frame_url = str(getattr(frame, "url", "") or "").lower()
                if "challenges.cloudflare.com" not in frame_url:
                    continue
                for selector in ('input[type="checkbox"]', '[role="checkbox"]', 'label'):
                    try:
                        locator = frame.locator(selector)
                        locator = getattr(locator, "first", locator)
                        if locator.is_visible():
                            locator.click(timeout=3000)
                            return True
                    except Exception:
                        continue
        except Exception:
            return False
        return False

    @staticmethod
    def _submit_attendance_with_token(page) -> bool:
        """Turnstile 已签发 token 但页面回调未触发时，补交原 attendance 表单。"""
        script = """
            () => {
                const form = document.querySelector('form#attendance');
                if (!form) return false;
                const fields = form.querySelectorAll(
                    'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
                );
                const token = Array.from(fields).map((item) => item.value).find(Boolean);
                if (!token) return false;
                if (typeof form.requestSubmit === 'function') form.requestSubmit();
                else form.submit();
                return true;
            }
        """
        try:
            return bool(page.evaluate(script))
        except Exception:
            return False

    @staticmethod
    def _wait_browser_page(page, seconds: int) -> None:
        try:
            page.wait_for_timeout(int(seconds * 1000))
        except Exception:
            time.sleep(seconds)
