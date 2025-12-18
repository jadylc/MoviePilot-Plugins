# -*- coding: utf-8 -*-
from typing import Dict, Optional
from app.log import logger
from . import _IInviterInfoHandler


class MTeamInviterInfoHandler(_IInviterInfoHandler):
    """
    M-Team站点邀请人信息获取类
    """
    # 匹配的站点Url
    site_url = "https://kp.m-team.cc"
    # 站点名称
    site_name = "M-Team"

    @classmethod
    def match(cls, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点邀请人信息获取类
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的get_inviter_info方法
        """
        if url and "m-team" in url:
            return True
        return False

    def get_inviter_info(self, site_info: dict) -> Dict[str, Optional[str]]:
        """
        获取M-Team站点的邀请人信息
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 邀请人信息字典
        """
        logger.info(f"开始获取M-Team站点 {site_info.get('name')} 的邀请人信息")
        logger.debug(f"站点信息详情: {site_info}")
        
        site_url = site_info.get("url", "")
        
        if not site_url:
            logger.error("获取M-Team站点信息失败：未提供站点URL")
            return None

        # 构建用户详情页URL
        user_id = self._get_user_id(site_info)
        if user_id:
            user_url = f"{site_url}/profile/detail/{user_id}"
        else:
            user_url = f"{site_url}/profile"
        
        logger.info(f"构建的用户详情页URL: {user_url}")
        
        # 获取页面内容
        html_content = self.get_page_source(user_url, site_info)
        
        if not html_content:
            logger.error("获取M-Team用户页面失败")
            return None
            
        logger.info(f"成功获取页面: {user_url}")
        logger.debug(f"页面内容大小: {len(html_content)} 字节")

        from lxml import etree
        html = etree.HTML(html_content)
        if not html:
            logger.error("解析M-Team用户页面失败")
            return None
        logger.info("成功解析M-Team用户页面")
        
        # 尝试多种XPath提取邀请人信息
        inviter_xpaths = [
            # 可能的邀请人信息XPath
            "//div[contains(@class, 'profile-info')]//div[contains(text(), '邀请人')]/following-sibling::div[1]",
            "//div[contains(@class, 'user-info')]//div[contains(text(), '邀请人')]/following-sibling::div[1]",
            "//table//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//div[contains(@class, 'inviter')]/text()",
            "//span[contains(@class, 'inviter-name')]/text()",
            "//a[contains(@href, 'profile')]/text()"
        ]
        logger.info(f"使用 {len(inviter_xpaths)} 种XPath尝试提取邀请人信息")

        inviter_element = None
        found_xpath = None
        for i, xpath in enumerate(inviter_xpaths):
            logger.debug(f"尝试第 {i+1} 种XPath: {xpath}")
            elements = html.xpath(xpath)
            if elements:
                logger.info(f"XPath {i+1} 匹配到 {len(elements)} 个元素")
                inviter_element = elements[0]
                found_xpath = xpath
                break
        
        if not inviter_element:
            logger.info("M-Team未找到邀请人信息，返回'无'")
            return {
                "inviter_name": "无",
                "inviter_id": "",
                "inviter_email": ""
            }
        
        logger.info(f"使用XPath: {found_xpath} 找到邀请人元素")
        
        # 获取邀请人名称
        inviter_name = ""
        full_text = "".join(inviter_element.xpath(".//text()")).strip()
        logger.info(f"获取到邀请人元素的完整文本: {full_text}")
        
        # 清理邀请人名称
        if full_text:
            import re
            # 移除可能的标签和标点
            inviter_name = re.sub(r'[\s:：,.;，。；"\'\[\]()（）【】]+$', '', full_text.strip())
            # 移除HTML实体
            inviter_name = re.sub(r'&[a-zA-Z0-9]+;', '', inviter_name)
            # 移除多余的空格
            inviter_name = re.sub(r'\s+', ' ', inviter_name).strip()
            logger.info(f"最终提取到的邀请人名称: {inviter_name}")
        
        # 获取邀请人ID
        inviter_id = ""
        link_elements = inviter_element.xpath(".//a/@href")
        if link_elements:
            found_link = link_elements[0].strip()
            logger.info(f"从链接中提取到邀请人信息URL: {found_link}")
            # 尝试从URL中提取ID
            import re
            id_match = re.search(r"profile/detail/(\d+)", found_link)
            if id_match:
                inviter_id = id_match.group(1)
                logger.info(f"提取到的邀请人ID: {inviter_id}")
        else:
            logger.info("未找到邀请人相关的链接")
        
        # M-Team站点可能不公开邮箱信息
        inviter_email = ""
        
        return {
            "inviter_name": inviter_name,
            "inviter_id": inviter_id,
            "inviter_email": inviter_email
        }

    def _get_user_id(self, site_info: dict) -> Optional[str]:
        """
        获取用户ID
        :param site_info: 站点信息
        :return: 用户ID
        """
        try:
            site_url = site_info.get("url", "")
            if not site_url:
                logger.error("获取用户ID失败: 站点URL为空")
                return None

            # 尝试从个人页面URL中提取ID
            import re
            id_match = re.search(r"profile/detail/(\d+)", site_url)
            if id_match:
                user_id = id_match.group(1)
                logger.info(f"从URL中提取到用户ID: {user_id}")
                return user_id
            
            # 尝试从会话中获取用户ID
            session = self._init_session(site_info)
            
            # 访问个人主页
            user_url = f"{site_url}/profile"
            response = session.get(user_url, timeout=(5, 20))
            response.raise_for_status()
            
            # 尝试从响应URL中提取ID
            if "profile/detail" in response.url:
                id_match = re.search(r"profile/detail/(\d+)", response.url)
                if id_match:
                    user_id = id_match.group(1)
                    logger.info(f"从响应URL中提取到用户ID: {user_id}")
                    return user_id
            
            logger.info("未找到用户ID")
            return None
        except Exception as e:
            logger.error(f"获取用户ID失败: {str(e)}")
            return None