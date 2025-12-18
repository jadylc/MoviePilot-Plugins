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
            '//div[@class="ant-card-body"]/table[1]/tbody/tr[td[text()="邀請人"]]/td[2]'
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
        inviter_name = ""
        if full_text:
            import re
            # 移除可能的标签和标点
            inviter_name = re.sub(r'[\s:：,.;，。；"\'\[\]()（）【】]+$', '', full_text.strip())
            # 移除HTML实体
            inviter_name = re.sub(r'&[a-zA-Z0-9]+;', '', inviter_name)
            # 移除多余的空格
            inviter_name = re.sub(r'\s+', ' ', inviter_name).strip()
            logger.info(f"从文本中提取到的邀请人名称: {inviter_name}")
        
        # 如果文本中未提取到名称，尝试从strong标签中提取
        if not inviter_name:
            strong_elements = inviter_element.xpath(".//strong/text()")
            if strong_elements:
                inviter_name = strong_elements[0].strip()
                logger.info(f"从strong标签中提取到的邀请人名称: {inviter_name}")
        
        # 如果strong标签中未提取到名称，尝试从span标签中提取
        if not inviter_name:
            span_elements = inviter_element.xpath(".//span/text()")
            if span_elements:
                inviter_name = span_elements[0].strip()
                logger.info(f"从span标签中提取到的邀请人名称: {inviter_name}")
        
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
        
        # 最终检查邀请人信息
        if not inviter_name and not inviter_id:
            logger.info("M-Team未找到邀请人信息，返回'无'")
            return {
                "inviter_name": "无",
                "inviter_id": "",
                "inviter_email": ""
            }
        
        logger.info(f"最终提取到的邀请人名称: {inviter_name}")
        logger.info(f"最终提取到的邀请人ID: {inviter_id}")
        
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
        site_name = site_info.get("name", "")
        api_key = site_info.get("apikey", "")
        authorization = site_info.get("token", "")  # 使用token字段作为Authorization
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
            
            # 尝试从Cookie中提取uid
            cookies = session.cookies
            uid = cookies.get("uid")
            if uid:
                logger.info(f"从Cookie中提取到用户ID: {uid}")
                return uid
            
            # 尝试通过API获取用户ID
            try:
                # 检查API认证信息
                if not api_key or not authorization:
                    logger.error(f"站点 {site_name} API认证信息不完整")
                    return None
                # 提取API域名
                api_domain = self._extract_api_domain(site_url)
                api_base_url = f"https://api.{api_domain}/api"
                logger.info(f"站点 {site_name} 使用API基础URL: {api_base_url}")

                # 配置API请求头 (根据最新参考调整，但恢复 Authorization)
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": site_info.get("ua", "Mozilla/5.0"),
                    "Accept": "application/json, text/plain, */*",
                    "Authorization": authorization,  # 恢复 Authorization
                    "x-api-key": api_key,
                    # "ts": str(int(time.time())) # 保持移除 ts
                }

                # 重置会话并添加API认证头
                session.headers.clear()
                session.headers.update(headers)

                # 步骤1: 获取用户信息
                user_data = self._get_user_profile(api_base_url, session, site_name)
                if not user_data:
                    return None

                # 提取用户ID、永久邀请和临时邀请数量
                user_id = user_data.get("id")
                if not user_id:
                    return None
                return user_id
            except Exception as e:
                logger.warning(f"通过API获取用户ID失败: {str(e)}")

            logger.info("未找到用户ID")
            return None
        except Exception as e:
            logger.error(f"获取用户ID失败: {str(e)}")
            return None



    def _extract_api_domain(self, url: str) -> str:
        """
        从URL提取API域名
        :param url: 站点URL
        :return: API域名
        """
        if not url:
            return "m-team.cc"
            
        # 移除协议前缀和路径
        domain = url.lower()
        domain = domain.replace("https://", "").replace("http://", "").split("/")[0]
        
        # 直接使用API域名
        if domain in ["api.m-team.cc", "api.m-team.io"]:
            # 截取m-team.cc或m-team.io部分
            return domain.replace("api.", "")
            
        # 特殊处理m-team子域名
        if domain.startswith("www."):
            domain = domain[4:]
        elif any(domain.startswith(prefix) for prefix in ["pt.", "kp.", "zp."]):
            domain = domain[3:]
            
        # 如果域名包含m-team，提取主域名
        if "m-team.io" in domain:
            logger.info(f"使用m-team.io作为API域名")
            return "m-team.io"
        if "m-team.cc" in domain:
            logger.info(f"使用m-team.cc作为API域名")
            return "m-team.cc"
            
        # 默认返回m-team.cc
        logger.info(f"无法识别域名 {domain}，使用默认m-team.cc作为API域名")
        return "m-team.cc"

