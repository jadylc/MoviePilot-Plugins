# -*- coding: utf-8 -*-
from typing import Dict, Optional

from app.log import logger
from app.utils.http import RequestUtils
from app.core.config import settings

from . import _IInviterInfoHandler


class NexusPHPInviterInfoHandler(_IInviterInfoHandler):
    """
    NexusPHP通用邀请人信息获取类，支持大部分NexusPHP框架的PT站点
    """
    # 这里不设置具体的site_url，因为这是一个通用处理类
    site_url = ""
    site_name = "NexusPHP"

    def match(self, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点邀请人信息获取类
        这个通用类默认不匹配任何站点，主要由主插件直接调用作为通用处理器
        :param url: 站点Url
        :return: 是否匹配
        """
        # 主插件会直接调用这个处理器，所以这里不需要匹配特定URL
        return False

    def get_inviter_info(self, site_info: dict) -> Dict[str, Optional[str]]:
        """
        获取NexusPHP站点的邀请人信息
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 邀请人信息字典
        """
        logger.info(f"开始获取NexusPHP站点 {site_info.get('name')} 的邀请人信息")
        cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout", 20)
        site_url = site_info.get("url", "")

        if not site_url:
            logger.error("获取NexusPHP站点信息失败：未提供站点URL")
            return None

        # 构建用户详情页URL
        user_url = f"{site_url}/userdetails.php?id=0"
        logger.info(f"构建用户详情页URL: {user_url}")

        # 获取页面源码
        headers = {
            "User-Agent": ua,
            "Cookie": cookie
        }
        logger.info(f"使用Headers: {headers}")
        res = RequestUtils(headers=headers,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout).get_res(url=user_url)
        if res:
            logger.info(f"获取页面状态码: {res.status_code}")
            if res.status_code != 200:
                logger.error(f"获取NexusPHP用户页面失败: {res.status_code}")
                return None
        else:
            logger.error("获取NexusPHP用户页面失败: 无响应")
            return None

        from lxml import etree
        html = etree.HTML(res.text)
        if not html:
            logger.error("解析NexusPHP用户页面失败")
            return None
        logger.info("成功解析NexusPHP用户页面")

        # 尝试多种常见的邀请人信息XPath
        inviter_xpaths = [
            # 表格结构（用户提供的HTML结构）
            "//td[text()='邀请人']/following-sibling::td[1]",
            "//td[@class='rowhead' and contains(text(), '邀请人')]/following-sibling::td[1]",
            # 列表结构
            "//div[@class='userinfo']//li[contains(text(), '邀请人')]",
            "//div[@class='profile']//li[contains(text(), '邀请人')]",
            "//div[@id='outer']//li[contains(text(), '邀请人')]",
            "//li[contains(text(), '邀请人')]",
            "//*[contains(text(), '邀请人')]/.."
        ]
        logger.info(f"使用 {len(inviter_xpaths)} 种XPath尝试提取邀请人信息")

        inviter_element = None
        for i, xpath in enumerate(inviter_xpaths):
            logger.info(f"尝试第 {i+1} 种XPath: {xpath}")
            elements = html.xpath(xpath)
            if elements:
                logger.info(f"找到邀请人元素: {elements[0]}")
                inviter_element = elements[0]
                break

        if not inviter_element:
            logger.info("NexusPHP未找到邀请人信息，返回'无'")
            return {
                "inviter_name": "无",
                "inviter_id": "",
                "inviter_email": ""
            }

        # 获取邀请人名称
        logger.info("开始提取邀请人名称")
        inviter_name = ""
        
        # 尝试从链接中获取名称
        logger.info("尝试从链接中获取邀请人名称")
        name_elements = inviter_element.xpath(".//a/text()")
        if name_elements:
            logger.info(f"从链接中提取到邀请人名称: {name_elements[0]}")
            inviter_name = name_elements[0].strip()
        else:
            # 尝试直接从文本中获取名称
            logger.info("从链接中未找到邀请人名称，尝试直接从文本中获取")
            text = inviter_element.xpath("./text()")
            if text:
                text = text[0].strip()
                logger.info(f"从文本中提取到原始内容: {text}")
                if "邀请人" in text:
                    # 尝试解析类似 "邀请人：用户名" 的格式
                    if "：" in text:
                        logger.info("使用中文冒号解析邀请人名称")
                        inviter_name = text.split("：")[1].strip()
                    elif ":" in text:
                        logger.info("使用英文冒号解析邀请人名称")
                        inviter_name = text.split(":")[1].strip()
                    logger.info(f"解析后得到邀请人名称: {inviter_name}")
            else:
                logger.info("未找到邀请人名称相关的文本内容")

        logger.info(f"最终提取到的邀请人名称: {inviter_name}")
        
        # 如果邀请人名称为"匿名"，则不获取更多信息
        if inviter_name == "匿名":
            logger.info("邀请人为匿名用户，不获取更多信息")
            return {
                "inviter_name": "匿名",
                "inviter_id": "",
                "inviter_email": ""
            }

        # 获取邀请人ID
        logger.info("开始提取邀请人ID")
        inviter_id = ""
        link_elements = inviter_element.xpath(".//a/@href")
        if link_elements:
            link = link_elements[0]
            logger.info(f"从链接中提取到邀请人信息URL: {link}")
            if "id=" in link:
                logger.info("从URL中提取邀请人ID")
                inviter_id = link.split("id=")[1].split("&")[0]
                logger.info(f"提取到的邀请人ID: {inviter_id}")
            else:
                logger.info("URL中未包含邀请人ID信息")
        else:
            logger.info("未找到邀请人相关的链接")

        # 如果有邀请人ID，尝试获取其邮箱（如果隐私设置允许）
        inviter_email = ""
        if inviter_id:
            inviter_email = self.__get_user_email(site_url, inviter_id, site_info)

        return {
            "inviter_name": inviter_name,
            "inviter_id": inviter_id,
            "inviter_email": inviter_email
        }

    def __get_user_email(self, site_url: str, user_id: str, site_info: dict) -> str:
        """
        获取NexusPHP用户邮箱（如果隐私设置允许）
        :param site_url: 站点URL
        :param user_id: 用户ID
        :param site_info: 站点信息
        :return: 用户邮箱
        """
        logger.info(f"开始获取用户ID {user_id} 的邮箱信息")
        cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout", 20)

        url = f"{site_url}/userdetails.php?id={user_id}"
        logger.info(f"构建用户详情页URL: {url}")
        headers = {
            "User-Agent": ua,
            "Cookie": cookie
        }
        logger.info(f"使用Headers: {headers}")
        
        logger.info("开始发送HTTP请求获取用户详情页")
        res = RequestUtils(headers=headers,
                           proxies=settings.PROXY if proxy else None,
                           timeout=timeout).get_res(url=url)
        
        if not res:
            logger.error("获取用户详情页失败: 无响应")
            return ""
            
        logger.info(f"获取页面状态码: {res.status_code}")
        if res.status_code != 200:
            logger.error(f"获取用户详情页失败: {res.status_code}")
            return ""

        from lxml import etree
        logger.info("开始解析用户详情页HTML")
        html = etree.HTML(res.text)
        if not html:
            logger.error("解析用户详情页HTML失败")
            return ""
        logger.info("成功解析用户详情页HTML")

        # 尝试多种常见的邮箱信息XPath
        email_xpaths = [
            # 表格结构（用户提供的HTML结构）- 从链接中提取
            "//td[text()='邮箱']/following-sibling::td[1]//a/@href",
            "//td[@class='rowhead' and contains(text(), '邮箱')]/following-sibling::td[1]//a/@href",
            # 表格结构 - 直接提取文本
            "//td[text()='邮箱']/following-sibling::td[1]/text()",
            "//td[@class='rowhead' and contains(text(), '邮箱')]/following-sibling::td[1]/text()",
            # 列表结构 - 从链接中提取
            "//div[@class='userinfo']//li[contains(text(), '邮箱')]//a/@href",
            "//div[@class='profile']//li[contains(text(), '邮箱')]//a/@href",
            "//div[@id='outer']//li[contains(text(), '邮箱')]//a/@href",
            "//li[contains(text(), '邮箱')]//a/@href",
            # 列表结构 - 直接提取文本
            "//div[@class='userinfo']//li[contains(text(), '邮箱')]/text()",
            "//div[@class='profile']//li[contains(text(), '邮箱')]/text()",
            "//div[@id='outer']//li[contains(text(), '邮箱')]/text()",
            "//li[contains(text(), '邮箱')]/text()",
            "//*[contains(text(), '邮箱')]/following-sibling::*/text()"
        ]
        logger.info(f"使用 {len(email_xpaths)} 种XPath尝试提取邮箱信息")

        email_text = ""
        for i, xpath in enumerate(email_xpaths):
            logger.info(f"尝试第 {i+1} 种XPath: {xpath}")
            elements = html.xpath(xpath)
            if elements:
                logger.info(f"找到邮箱元素: {elements[0]}")
                email_text = elements[0].strip()
                break

        if not email_text:
            logger.info("未找到邮箱信息")
            return ""
        
        logger.info(f"提取到邮箱原始文本: {email_text}")

        # 处理mailto链接
        if email_text.startswith("mailto:"):
            logger.info("邮箱文本是mailto链接，进行处理")
            email_text = email_text[7:].strip()
        # 处理普通文本格式
        elif "邮箱" in email_text:
            logger.info("邮箱文本是普通文本格式，进行处理")
            if "：" in email_text:
                email_text = email_text.split("：")[1].strip()
            elif ":" in email_text:
                email_text = email_text.split(":")[1].strip()
        
        logger.info(f"最终获取到的邮箱信息: {email_text}")
        return email_text
