# -*- coding: utf-8 -*-
import re
from abc import ABCMeta, abstractmethod
from typing import Dict, Optional

from app.log import logger
from app.utils.http import RequestUtils
from app.utils.string import StringUtils


class _IInviterInfoHandler(metaclass=ABCMeta):
    """
    实现站点邀请人信息获取的基类，所有站点邀请人信息获取类都需要继承此类，并实现match和get_inviter_info方法
    实现类放置到inviterinfo/sites目录下将会自动加载
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = ""
    # 站点名称
    site_name = ""

    @abstractmethod
    def match(self, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点邀请人信息获取类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的get_inviter_info方法
        """
        if StringUtils.url_equal(url, self.site_url):
            return True
        return False

    @abstractmethod
    def get_inviter_info(self, site_info: dict) -> Dict[str, Optional[str]]:
        """
        获取邀请人信息
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 邀请人信息字典，包含inviter_name、inviter_id、inviter_email等字段
        """
        pass

    @staticmethod
    def get_page_source(url: str, cookie: str, ua: str, proxy: bool = False, timeout: int = 20) -> str:
        """
        获取页面源码
        :param url: Url地址
        :param cookie: Cookie
        :param ua: UA
        :param proxy: 是否使用代理
        :param timeout: 请求超时时间，单位秒
        :return: 页面源码
        """
        headers = {
            "User-Agent": ua,
            "Cookie": cookie
        }
        res = RequestUtils(headers=headers,
                           proxies=proxy,
                           timeout=timeout).get_res(url=url)
        if res is not None:
            return res.text
        return ""

    def parse_response(self, html_content: str, xpath_rules: Dict[str, str]) -> Dict[str, Optional[str]]:
        """
        解析HTML内容，提取邀请人信息
        :param html_content: HTML内容
        :param xpath_rules: XPath规则字典
        :return: 邀请人信息字典
        """
        from lxml import etree
        try:
            tree = etree.HTML(html_content)
            result = {}
            for key, xpath in xpath_rules.items():
                elements = tree.xpath(xpath)
                result[key] = elements[0].strip() if elements else None
            return result
        except Exception as e:
            logger.error(f"解析邀请人信息失败: {str(e)}")
            return {}
