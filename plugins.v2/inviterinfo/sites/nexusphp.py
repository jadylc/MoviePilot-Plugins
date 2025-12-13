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
        :param url: 站点Url
        :return: 是否匹配
        """
        # 通用NexusPHP处理器，主插件会直接调用，但我们也可以尝试识别常见的NexusPHP站点特征
        return False
    
    def is_nexusphp_site(self, html_content: str) -> bool:
        """
        判断一个站点是否为NexusPHP站点
        :param html_content: 站点页面HTML内容
        :return: 是否为NexusPHP站点
        """
        if not html_content:
            return False
            
        # NexusPHP特征列表，匹配任意一个即可
        nexusphp_features = [
            # 常见的NexusPHP CSS类
            r'class=["\']userdetails["\']',
            r'class=["\']userinfo["\']',
            r'class=["\']profile["\']',
            r'class=["\']rowhead["\']',
            r'class=["\']torrents["\']',
            r'class=["\']torrenttable["\']',
            
            # 常见的NexusPHP JavaScript变量
            r'var\s+userid\s*=',
            r'var\s+username\s*=',
            r'var\s+passhash\s*=',
            r'var\s+baseurl\s*=',
            
            # 常见的NexusPHP页面元素
            r'<a[^>]+href=["\']userdetails\.php\?id=',
            r'<a[^>]+href=["\']torrents\.php',
            r'<a[^>]+href=["\']upload\.php',
            r'<a[^>]+href=["\']messages\.php',
            r'<a[^>]+href=["\']friends\.php',
            
            # 常见的NexusPHP文本
            r'邀请人',
            r'Inviter',
            r'上传量',
            r'下载量',
            r'做种时间',
            r'下载时间',
            r'分享率',
            r'Share Ratio',
            r'Uploaded',
            r'Downloaded',
            r'Seeding Time',
            r'Leeching Time',
            
            # 其他NexusPHP特征
            r'powered\s+by\s+nexusphp',
            r'NexusPHP\s+v\d+\.\d+',
            r'nexusphp\.com',
        ]
        
        # 尝试匹配任意一个特征
        import re
        for feature in nexusphp_features:
            if re.search(feature, html_content, re.IGNORECASE):
                return True
                
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
                # 如果用户详情页失败，尝试获取首页
                logger.info("尝试获取站点首页")
                home_res = RequestUtils(headers=headers,
                                       proxies=settings.PROXY if proxy else None,
                                       timeout=timeout).get_res(url=site_url)
                if home_res and home_res.status_code == 200:
                    logger.info("成功获取站点首页，检查是否为NexusPHP站点")
                    is_nexusphp = self.is_nexusphp_site(home_res.text)
                    logger.info(f"站点{site_info.get('name')}是否为NexusPHP站点: {is_nexusphp}")
                return None
        else:
            logger.error("获取NexusPHP用户页面失败: 无响应")
            return None

        # 检查是否为NexusPHP站点
        logger.info("检查是否为NexusPHP站点")
        is_nexusphp = self.is_nexusphp_site(res.text)
        logger.info(f"站点{site_info.get('name')}是否为NexusPHP站点: {is_nexusphp}")

        from lxml import etree
        html = etree.HTML(res.text)
        if not html:
            logger.error("解析NexusPHP用户页面失败")
            return None
        logger.info("成功解析NexusPHP用户页面")

        # 尝试多种常见的邀请人信息XPath
        inviter_xpaths = [
            # 表格结构（用户提供的HTML结构） - 精确匹配
            "//td[@class='rowhead' and text()='邀请人']/following-sibling::td[1]",
            "//td[@class='rowhead nowrap' and text()='邀请人']/following-sibling::td[1]",
            "//td[text()='邀请人']/following-sibling::td[1]",
            "//td[@class='rowhead' and contains(text(), '邀请人')]/following-sibling::td[1]",
            "//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//td[text()='Inviter']/following-sibling::td[1]",
            "//td[@class='rowhead' and text()='Inviter']/following-sibling::td[1]",
            "//td[@class='rowhead' and contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            # 更复杂的表格结构变体
            "//table[@class='userdetails']//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[@class='userinfo']//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[@class='profile']//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[@class='userdetails']//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[@class='userinfo']//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[@class='profile']//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            # 更多表格结构变体
            "//table[contains(@class, 'userdetails')]//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[contains(@class, 'userinfo')]//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[contains(@class, 'profile')]//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[contains(@class, 'userdetails')]//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[contains(@class, 'userinfo')]//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[contains(@class, 'profile')]//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[@id='userdetails']//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[@id='userinfo']//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[@id='profile']//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            "//table[@id='userdetails']//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[@id='userinfo']//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            "//table[@id='profile']//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            # 表格行内的所有元素
            "//tr[contains(., '邀请人')]//td[position()>1]",
            "//tr[contains(., 'Inviter')]//td[position()>1]",
            "//tr[contains(., '上家')]//td[position()>1]",
            "//tr[contains(., '上级')]//td[position()>1]",
            "//tr[contains(., '推荐人')]//td[position()>1]",
            "//tr[contains(., 'Referrer')]//td[position()>1]",
            "//tr[contains(., 'Sponsor')]//td[position()>1]",
            # 列表结构
            "//div[@class='userinfo']//li[contains(text(), '邀请人')]",
            "//div[@class='profile']//li[contains(text(), '邀请人')]",
            "//div[@id='outer']//li[contains(text(), '邀请人')]",
            "//li[contains(text(), '邀请人')]",
            "//div[@class='userinfo']//li[contains(text(), 'Inviter')]",
            "//div[@class='profile']//li[contains(text(), 'Inviter')]",
            "//div[@id='outer']//li[contains(text(), 'Inviter')]",
            "//li[contains(text(), 'Inviter')]",
            # 列表结构变体
            "//ul[@class='userinfo']//li[contains(text(), '邀请人')]",
            "//ul[@class='profile']//li[contains(text(), '邀请人')]",
            "//ul[@class='userdetails']//li[contains(text(), '邀请人')]",
            "//ul[@class='userinfo']//li[contains(text(), 'Inviter')]",
            "//ul[@class='profile']//li[contains(text(), 'Inviter')]",
            "//ul[@class='userdetails']//li[contains(text(), 'Inviter')]",
            "//ol[@class='userinfo']//li[contains(text(), '邀请人')]",
            "//ol[@class='profile']//li[contains(text(), '邀请人')]",
            "//ol[@class='userdetails']//li[contains(text(), '邀请人')]",
            "//ol[@class='userinfo']//li[contains(text(), 'Inviter')]",
            "//ol[@class='profile']//li[contains(text(), 'Inviter')]",
            "//ol[@class='userdetails']//li[contains(text(), 'Inviter')]",
            # 列表项中的span和div
            "//li[contains(text(), '邀请人')]//span[not(contains(text(), '邀请人'))]",
            "//li[contains(text(), 'Inviter')]//span[not(contains(text(), 'Inviter'))]",
            "//li[contains(text(), '邀请人')]//div[not(contains(text(), '邀请人'))]",
            "//li[contains(text(), 'Inviter')]//div[not(contains(text(), 'Inviter'))]",
            # 通用结构
            "//*[contains(text(), '邀请人')]/following-sibling::*",
            "//*[text()='邀请人']/following-sibling::*",
            "//*[contains(text(), 'Inviter')]/following-sibling::*",
            "//*[text()='Inviter']/following-sibling::*",
            "//*[contains(text(), '邀请人')]/..",
            "//*[contains(text(), 'Inviter')]/..",
            # 通用结构变体
            "//*[contains(text(), '邀请人')]/following::*[1]",
            "//*[contains(text(), 'Inviter')]/following::*[1]",
            "//*[text()='邀请人']/following::*[1]",
            "//*[text()='Inviter']/following::*[1]",
            "//*[contains(text(), '邀请人')]/following::text()[1]",
            "//*[contains(text(), 'Inviter')]/following::text()[1]",
            "//*[text()='邀请人']/following::text()[1]",
            "//*[text()='Inviter']/following::text()[1]",
            # 更通用的查找（包含各种标签）
            "//tr[contains(., '邀请人')]",
            "//tr[contains(., 'Inviter')]",
            "//div[contains(text(), '邀请人')]",
            "//div[contains(text(), 'Inviter')]",
            "//span[contains(text(), '邀请人')]",
            "//span[contains(text(), 'Inviter')]",
            "//p[contains(text(), '邀请人')]",
            "//p[contains(text(), 'Inviter')]",
            "//div[@class='inviter']",
            "//span[@class='inviter']",
            "//div[contains(@class, 'inviter')]",
            "//span[contains(@class, 'inviter')]",
            "//div[@id='inviter']",
            "//span[@id='inviter']",
            "//p[@class='inviter']",
            "//p[@id='inviter']",
            # 更多标签组合
            "//div[contains(@class, 'info')]//*[contains(text(), '邀请人')]",
            "//div[contains(@class, 'info')]//*[contains(text(), 'Inviter')]",
            "//div[contains(@class, 'details')]//*[contains(text(), '邀请人')]",
            "//div[contains(@class, 'details')]//*[contains(text(), 'Inviter')]",
            "//div[contains(@class, 'user')]//*[contains(text(), '邀请人')]",
            "//div[contains(@class, 'user')]//*[contains(text(), 'Inviter')]",
            "//div[contains(@class, 'profile')]//*[contains(text(), '邀请人')]",
            "//div[contains(@class, 'profile')]//*[contains(text(), 'Inviter')]",
            "//div[contains(@class, 'member')]//*[contains(text(), '邀请人')]",
            "//div[contains(@class, 'member')]//*[contains(text(), 'Inviter')]",
            # 更多层级结构
            "//body//*[contains(text(), '邀请人')]/following-sibling::*",
            "//body//*[contains(text(), 'Inviter')]/following-sibling::*",
            "//div[@id='content']//*[contains(text(), '邀请人')]/following-sibling::*",
            "//div[@id='content']//*[contains(text(), 'Inviter')]/following-sibling::*",
            "//div[@class='container']//*[contains(text(), '邀请人')]/following-sibling::*",
            "//div[@class='container']//*[contains(text(), 'Inviter')]/following-sibling::*",
            "//div[@class='wrapper']//*[contains(text(), '邀请人')]/following-sibling::*",
            "//div[@class='wrapper']//*[contains(text(), 'Inviter')]/following-sibling::*",
            # 更多兄弟节点查找方式
            "//*[contains(text(), '邀请人')]/following-sibling::text()",
            "//*[contains(text(), 'Inviter')]/following-sibling::text()",
            "//*[text()='邀请人']/following-sibling::text()",
            "//*[text()='Inviter']/following-sibling::text()",
            # 中文变体
            "//*[contains(text(), '上家')]/following-sibling::*",
            "//*[contains(text(), '上级')]/following-sibling::*",
            "//*[contains(text(), '推荐人')]/following-sibling::*",
            "//*[contains(text(), '上家')]/following::*[1]",
            "//*[contains(text(), '上级')]/following::*[1]",
            "//*[contains(text(), '推荐人')]/following::*[1]",
            "//*[text()='上家']/following-sibling::*",
            "//*[text()='上级']/following-sibling::*",
            "//*[text()='推荐人']/following-sibling::*",
            "//*[text()='上家']/following::*[1]",
            "//*[text()='上级']/following::*[1]",
            "//*[text()='推荐人']/following::*[1]",
            "//*[contains(text(), '上家')]/following-sibling::text()",
            "//*[contains(text(), '上级')]/following-sibling::text()",
            "//*[contains(text(), '推荐人')]/following-sibling::text()",
            "//*[text()='上家']/following-sibling::text()",
            "//*[text()='上级']/following-sibling::text()",
            "//*[text()='推荐人']/following-sibling::text()",
            # 英文变体
            "//*[contains(text(), 'Referrer')]/following-sibling::*",
            "//*[contains(text(), 'Sponsor')]/following-sibling::*",
            "//*[contains(text(), 'Referrer')]/following::*[1]",
            "//*[contains(text(), 'Sponsor')]/following::*[1]",
            "//*[text()='Referrer']/following-sibling::*",
            "//*[text()='Sponsor']/following-sibling::*",
            "//*[text()='Referrer']/following::*[1]",
            "//*[text()='Sponsor']/following::*[1]",
            "//*[contains(text(), 'Referrer')]/following-sibling::text()",
            "//*[contains(text(), 'Sponsor')]/following-sibling::text()",
            "//*[text()='Referrer']/following-sibling::text()",
            "//*[text()='Sponsor']/following-sibling::text()",
            # 更多中文标签变体
            "//*[contains(text(), '邀请人信息')]/following-sibling::*",
            "//*[contains(text(), '邀请人资料')]/following-sibling::*",
            "//*[contains(text(), '邀请我的人')]/following-sibling::*",
            "//*[contains(text(), '邀请人信息')]/following::*[1]",
            "//*[contains(text(), '邀请人资料')]/following::*[1]",
            "//*[contains(text(), '邀请我的人')]/following::*[1]",
            "//*[contains(text(), '邀请人ID')]/following-sibling::*",
            "//*[contains(text(), '邀请人ID')]/following::*[1]",
            "//*[contains(text(), '注册来源')]/following-sibling::*",
            "//*[contains(text(), '注册来源')]/following::*[1]",
            # 更多英文标签变体
            "//*[contains(text(), 'Inviter Info')]/following-sibling::*",
            "//*[contains(text(), 'Inviter Details')]/following-sibling::*",
            "//*[contains(text(), 'Who Invited Me')]/following-sibling::*",
            "//*[contains(text(), 'Inviter Info')]/following::*[1]",
            "//*[contains(text(), 'Inviter Details')]/following::*[1]",
            "//*[contains(text(), 'Who Invited Me')]/following::*[1]",
            "//*[contains(text(), 'Inviter ID')]/following-sibling::*",
            "//*[contains(text(), 'Inviter ID')]/following::*[1]",
            "//*[contains(text(), 'Registration Source')]/following-sibling::*",
            "//*[contains(text(), 'Registration Source')]/following::*[1]",
        ]
        logger.info(f"使用 {len(inviter_xpaths)} 种XPath尝试提取邀请人信息")

        inviter_element = None
        found_xpath = None
        all_matches = []  # 记录所有匹配的XPath结果
        for i, xpath in enumerate(inviter_xpaths):
            logger.debug(f"尝试第 {i+1} 种XPath: {xpath}")
            elements = html.xpath(xpath)
            if elements:
                logger.info(f"XPath {i+1} 匹配到 {len(elements)} 个元素")
                # 记录所有匹配的元素的文本摘要
                for j, elem in enumerate(elements[:3]):  # 只记录前3个元素
                    elem_text = "".join(elem.xpath(".//text()")).strip()[:50] + "..." if len("".join(elem.xpath(".//text()")).strip()) > 50 else "".join(elem.xpath(".//text()")).strip()
                    logger.debug(f"  匹配元素 {j+1}: {elem_text}")
                all_matches.append((xpath, len(elements)))
                
                inviter_element = elements[0]
                found_xpath = xpath
                break
        
        # 记录所有匹配的XPath
        if all_matches:
            logger.debug(f"总共匹配到 {len(all_matches)} 种XPath:")
            for xpath, count in all_matches:
                logger.debug(f"  - {xpath} (匹配 {count} 个元素)")

        if not inviter_element:
            logger.info("NexusPHP未找到邀请人信息，返回'无'")
            # 添加详细调试信息
            page_preview = res.text[:2000] + "..." if len(res.text) > 2000 else res.text
            logger.debug(f"页面预览 (前2000字符): {page_preview}")
            
            # 查找页面中所有包含邀请人相关关键词的元素
            import re
            inviter_keywords = ["邀请人", "Inviter", "上家", "上级", "推荐人", "Referrer", "Sponsor"]
            matches = []
            for keyword in inviter_keywords:
                # 使用正则表达式查找包含关键词的文本片段
                keyword_matches = re.finditer(f'.{{0,50}}{re.escape(keyword)}.{{0,100}}', res.text, re.IGNORECASE)
                for match in keyword_matches:
                    matches.append((keyword, match.group().strip()))
            
            if matches:
                logger.debug(f"页面中包含邀请人相关关键词的文本片段 (最多显示20个):")
                for i, (keyword, text) in enumerate(matches[:20]):
                    logger.debug(f"  {i+1}. [{keyword}] {text[:150]}..." if len(text) > 150 else f"  {i+1}. [{keyword}] {text}")
            else:
                logger.debug("页面中未找到任何邀请人相关关键词")
            
            # 记录页面的基本结构信息
            logger.debug("页面基本结构信息:")
            logger.debug(f"  - 页面长度: {len(res.text)} 字符")
            logger.debug(f"  - 是否包含userdetails.php: {'userdetails.php' in res.text}")
            logger.debug(f"  - 是否包含userinfo: {'userinfo' in res.text}")
            logger.debug(f"  - 是否包含profile: {'profile' in res.text}")
            logger.debug(f"  - 是否包含table标签: {'<table' in res.text}")
            logger.debug(f"  - 是否包含ul/ol标签: {'<ul' in res.text or '<ol' in res.text}")
            
            return {
                "inviter_name": "无",
                "inviter_id": "",
                "inviter_email": ""
            }
        
        logger.info(f"使用XPath: {found_xpath} 找到邀请人元素")

        # 获取邀请人名称
        logger.info("开始提取邀请人名称")
        inviter_name = ""
        
        # 获取元素的完整文本内容
        full_text = "".join(inviter_element.xpath(".//text()")).strip()
        logger.info(f"获取到邀请人元素的完整文本: {full_text}")
        
        # 添加调试信息：元素的XML结构
        from lxml import etree
        element_xml = etree.tostring(inviter_element, encoding="unicode", pretty_print=True)
        logger.debug(f"邀请人元素的XML结构: {element_xml}")
        
        # 定义可能的邀请人标签（更全面的变体）
        inviter_labels = [
            ("邀请人：", "邀请人:", "邀请人"),
            ("Inviter：", "Inviter:", "Inviter"),
            ("上家：", "上家:", "上家"),
            ("上级：", "上级:", "上级"),
            ("推荐人：", "推荐人:", "推荐人"),
            ("Referrer：", "Referrer:", "Referrer"),
            ("Sponsor：", "Sponsor:", "Sponsor"),
            ("邀请人信息：", "邀请人信息:", "邀请人信息"),
            ("邀请人资料：", "邀请人资料:", "邀请人资料"),
            ("邀请我的人：", "邀请我的人:", "邀请我的人"),
            ("Inviter Info：", "Inviter Info:", "Inviter Info"),
            ("Inviter Details：", "Inviter Details:", "Inviter Details"),
            ("Who Invited Me：", "Who Invited Me:", "Who Invited Me")
        ]
        
        # 尝试从链接中获取名称（优先）
        logger.info("尝试从链接中获取邀请人名称")
        
        # 先尝试处理<a>标签内有<b>标签的情况（用户提供的HTML结构）
        nested_name = inviter_element.xpath(".//a/b/text()")
        if nested_name:
            inviter_name = nested_name[0].strip()
            logger.info(f"从嵌套的<b>标签中提取到邀请人名称: {inviter_name}")
        else:
            # 尝试获取所有链接文本，包括嵌套标签内的文本
            name_elements = inviter_element.xpath(".//a//text()")
            if name_elements:
                for name in name_elements:
                    name = name.strip()
                    if name and not name.startswith("mailto:"):
                        logger.info(f"从链接中提取到邀请人名称: {name}")
                        inviter_name = name
                        break
        
        # 如果从链接中未找到，尝试从完整文本中提取
        if not inviter_name:
            logger.info("从链接中未找到邀请人名称，尝试从完整文本中提取")
            
            # 遍历所有可能的邀请人标签
            found_label = False
            for cn_colon, en_colon, label in inviter_labels:
                if label in full_text:
                    found_label = True
                    logger.info(f"找到邀请人标签: {label}")
                    
                    # 先尝试使用带冒号的完整标签
                    for colon_label in [cn_colon, en_colon]:
                        if colon_label in full_text:
                            logger.info(f"使用带冒号标签解析: {colon_label}")
                            parts = full_text.split(colon_label, 1)
                            if len(parts) > 1:
                                inviter_name = parts[1].strip()
                                break
                    
                    # 如果带冒号的标签失败，尝试不带冒号的标签
                    if not inviter_name:
                        logger.info(f"使用不带冒号标签解析: {label}")
                        # 使用正则表达式分割，确保只分割一次
                        import re
                        parts = re.split(re.escape(label), full_text, 1)
                        if len(parts) > 1:
                            inviter_name = parts[1].strip()
                    
                    if inviter_name:
                        break
            
            # 如果通过标签未能找到，尝试其他方法
            if not inviter_name:
                logger.info("未找到明确的邀请人标签或通过标签提取失败，尝试其他提取方法")
                
                # 尝试获取所有文本节点并筛选有意义的内容
                text_nodes = [text.strip() for text in inviter_element.xpath(".//text()") if text.strip()]
                logger.info(f"提取到所有文本节点: {text_nodes}")
                
                if text_nodes:
                    # 检查所有文本节点，查找邀请人信息
                    for i, node in enumerate(text_nodes):
                        # 检查节点是否包含邀请人相关标签
                        contains_label = any(label in node for _, _, label in inviter_labels)
                        if contains_label:
                            # 尝试获取下一个节点作为邀请人名称
                            for j in range(i + 1, len(text_nodes)):
                                next_node = text_nodes[j]
                                if next_node and not any(label in next_node for _, _, label in inviter_labels):
                                    inviter_name = next_node
                                    logger.info(f"从文本节点序列中提取到邀请人名称: {inviter_name}")
                                    break
                            if inviter_name:
                                break
                    
                    # 如果仍然没有找到，尝试获取所有非标签文本节点
                    if not inviter_name:
                        logger.info("尝试获取所有非标签文本节点")
                        non_label_nodes = [node for node in text_nodes if not any(label in node for _, _, label in inviter_labels)]
                        if non_label_nodes:
                            logger.debug(f"找到 {len(non_label_nodes)} 个非标签文本节点")
                            logger.debug(f"非标签文本节点列表: {non_label_nodes}")
                            
                            # 筛选掉无意义的节点
                            meaningful_nodes = [
                                node for node in non_label_nodes 
                                if node not in ["无", "None", "未知", "Unknown", "匿名", "Anonymous", "-", "--", "---", "N/A", "na", "NA", "none", "unknown"]
                                and len(node.strip()) > 0
                                and not all(c in ":：,.;，。；\"\'\[\]()（）【】-_ ".split() for c in node.strip())
                            ]
                            logger.debug(f"筛选后得到 {len(meaningful_nodes)} 个有意义的节点")
                            logger.debug(f"有意义的节点列表: {meaningful_nodes}")
                        
                        if meaningful_nodes:
                            # 优先选择长度适中的节点（可能是用户名）
                            # 按照长度排序，优先选择2-50个字符的节点（合理的用户名长度范围）
                            username_candidates = [node for node in meaningful_nodes if 2 <= len(node) <= 50]
                            
                            if username_candidates:
                                # 尝试选择包含字母或数字的节点（更可能是用户名）
                                alpha_num_candidates = [node for node in username_candidates if any(c.isalnum() for c in node)]
                                if alpha_num_candidates:
                                    # 选择最长的字母数字节点（更可能是完整的用户名）
                                    inviter_name = max(alpha_num_candidates, key=len)
                                    logger.info(f"从字母数字候选节点中提取到邀请人名称: {inviter_name}")
                                else:
                                    # 选择最长的候选节点
                                    inviter_name = max(username_candidates, key=len)
                                    logger.info(f"从候选节点中提取到邀请人名称: {inviter_name}")
                            elif meaningful_nodes:
                                # 如果没有合适长度的节点，尝试使用最长的非空节点
                                inviter_name = max(meaningful_nodes, key=lambda x: len(x.strip()))
                                logger.info(f"使用最长的有意义节点作为邀请人名称: {inviter_name}")
                            else:
                                # 使用第一个有意义的节点
                                inviter_name = meaningful_nodes[0]
                                logger.info(f"使用第一个有意义的非标签节点作为邀请人名称: {inviter_name}")
                    
                    # 最后的回退：使用元素的第一个文本内容
                    if not inviter_name:
                        logger.info("尝试直接获取元素的第一个文本内容")
                        first_text = inviter_element.xpath(".//text()[1]")
                        if first_text:
                            inviter_name = first_text[0].strip()
                            logger.info(f"使用元素的第一个文本内容作为邀请人名称: {inviter_name}")
            
            # 清理邀请人名称（移除可能的冗余字符）
        if inviter_name:
            logger.info(f"开始清理邀请人名称: {inviter_name}")
            original_name = inviter_name
            
            # 移除可能的标点符号和多余空格
            import re
            # 移除标签部分（如果有）
            for cn_colon, en_colon, label in inviter_labels:
                for colon_label in [cn_colon, en_colon, label]:
                    if colon_label in inviter_name:
                        logger.debug(f"移除标签: {colon_label}")
                        inviter_name = inviter_name.split(colon_label, 1)[-1].strip()
                        break
            
            logger.debug(f"移除标签后: {inviter_name}")
            
            # 移除可能的标点符号
            inviter_name = re.sub(r'[\s:：,.;，。；"\'\[\]()（）【】]+$', '', inviter_name.strip())
            logger.debug(f"移除标点符号后: {inviter_name}")
            
            # 移除HTML实体
            inviter_name = re.sub(r'&[a-zA-Z0-9]+;', '', inviter_name)
            logger.debug(f"移除HTML实体后: {inviter_name}")
            
            # 移除多余的空格
            inviter_name = re.sub(r'\s+', ' ', inviter_name).strip()
            logger.debug(f"移除多余空格后: {inviter_name}")
            
            # 移除特殊字符
            inviter_name = re.sub(r'[^\w\u4e00-\u9fa5\-_.@]+', '', inviter_name)
            logger.debug(f"移除特殊字符后: {inviter_name}")
            
            if original_name != inviter_name:
                logger.info(f"清理后得到邀请人名称: {inviter_name}")
            else:
                logger.info("邀请人名称无需清理")
                
                # 最后检查是否为空或无意义
                if inviter_name in ["", "无", "None", "未知", "Unknown", "匿名", "Anonymous", "-", "--", "---"]:
                    inviter_name = ""

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
            # 处理所有链接，优先选择包含id=的链接
            found_link = None
            for link in link_elements:
                link = link.strip()  # 去除链接中的前后空格
                if "id=" in link:
                    found_link = link
                    break
            
            # 如果没有找到包含id=的链接，使用第一个链接
            if not found_link and link_elements:
                found_link = link_elements[0].strip()
            
            if found_link:
                logger.info(f"从链接中提取到邀请人信息URL: {found_link}")
                if "id=" in found_link:
                    logger.info("从URL中提取邀请人ID")
                    # 提取ID，确保处理各种格式
                    id_part = found_link.split("id=")[-1].split("&")[0].strip()
                    # 确保ID是数字
                    if id_part.isdigit():
                        inviter_id = id_part
                    else:
                        # 尝试从链接路径中提取ID
                        import re
                        id_match = re.search(r"id=([0-9]+)", found_link)
                        if id_match:
                            inviter_id = id_match.group(1)
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
            # 表格结构（用户提供的HTML结构）- 从链接中提取，精确匹配
            "//td[@class='rowhead nowrap' and text()='邮箱']/following-sibling::td[1]//a/@href",
            "//td[@class='rowhead' and text()='邮箱']/following-sibling::td[1]//a/@href",
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
