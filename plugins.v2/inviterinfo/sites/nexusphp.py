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

    def match(self, site_url: str) -> bool:
        """
        判断是否匹配NexusPHP站点
        :param site_url: 站点URL
        :return: 是否匹配
        """
        # 排除已知的特殊站点
        special_sites = ["m-team", "totheglory", "hdchina", "butterfly", "dmhy", "蝶粉"]
        if any(site in site_url.lower() for site in special_sites):
            return False

        # 标准NexusPHP站点的URL特征
        nexus_features = [
            "php",                  # 大多数NexusPHP站点URL包含php
            "nexus",                # 部分站点URL中包含nexus
            "agsvpt",               # 红豆饭

            "audiences",            # 观众
            "hdpt",                 # HD盘他
            "wintersakura",         # 冬樱

            "hdmayi",               # 蚂蚁
            "u2.dmhy",              # U2
            "hddolby",              # 杜比
            "hdarea",               # 高清地带
            "pt.soulvoice",         # 聆音

            "ptsbao",               # PT书包
            "hdhome",               # HD家园
            "hdatmos",              # 阿童木
            "1ptba",                # 1PT
            "keepfrds",             # 朋友
            "moecat",               # 萌猫
            "springsunday"          # 春天
        ]

        # 如果URL中包含任何一个NexusPHP特征，则认为是NexusPHP站点
        site_url_lower = site_url.lower()
        for feature in nexus_features:
            if feature in site_url_lower:
                logger.debug(f"匹配到NexusPHP站点特征: {feature}")
                return True

        # 如果没有匹配到特征，但URL中包含PHP，也视为可能的NexusPHP站点
        if "php" in site_url_lower:
            logger.debug(f"URL中包含PHP，可能是NexusPHP站点: {site_url}")
            return True

        return False


    def get_inviter_info(self, site_info: dict) -> Dict[str, Optional[str]]:
        """
        获取NexusPHP站点的邀请人信息
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 邀请人信息字典
        """
        logger.info(f"开始获取NexusPHP站点 {site_info.get('name')} 的邀请人信息")
        logger.debug(f"站点信息详情: {site_info}")
        
        site_url = site_info.get("url", "")

        if not site_url:
            logger.error("获取NexusPHP站点信息失败：未提供站点URL")
            return None

        # 验证用户ID和登录状态
        logger.info("开始验证用户ID和登录状态")
        user_id = self._get_user_id(site_info)
        logger.info(f"获取到用户ID: {user_id}")
        
        # 构建用户详情页URL - 尝试多种可能的路径
        user_urls = []
        if user_id:
            user_urls.append(f"{site_url}/userdetails.php?id={user_id}")
            logger.debug(f"使用用户ID构建URL: {user_urls[-1]}")
        
        logger.info(f"构建的用户详情页URL列表: {user_urls}")
        
        # 尝试访问每个URL，直到成功获取到内容
        html_content = ""
        final_user_url = ""
        for user_url in user_urls:
            logger.info(f"尝试访问URL: {user_url}")
            html_content = self.get_page_source(user_url, site_info)
            
            if html_content:
                logger.info(f"成功获取页面: {user_url}")
                logger.debug(f"页面内容大小: {len(html_content)} 字节")
                final_user_url = user_url
                break
            else:
                logger.info(f"获取页面失败: {user_url}")
                
        if not html_content:
            logger.error("所有用户详情页URL都无法访问")
            return None
            
        logger.info(f"最终使用URL: {final_user_url} 获取页面内容")

        from lxml import etree
        html = etree.HTML(html_content)
        if not html:
            logger.error("解析NexusPHP用户页面失败")
            return None
        logger.info("成功解析NexusPHP用户页面")
        logger.debug("HTML解析树构建完成")

        # 核心NexusPHP表格结构邀请人信息XPath（仅保留NP核心结构规则）
        inviter_xpaths = [
            # 表格结构（NP核心结构） - 精确匹配
            # "//td[@class='rowhead' and text()='邀请人']/following-sibling::td[1]",
            "//td[@class='rowhead nowrap' and text()='邀请人']/following-sibling::td[1]",
            # "//td[@class='rowhead' and contains(text(), '邀请人')]/following-sibling::td[1]",
            "//td[text()='邀请人']/following-sibling::td[1]",
            # "//td[contains(text(), '邀请人')]/following-sibling::td[1]",
            
            # 英文版本
            # "//td[@class='rowhead' and text()='Inviter']/following-sibling::td[1]",
            # "//td[@class='rowhead' and contains(text(), 'Inviter')]/following-sibling::td[1]",
            # "//td[text()='Inviter']/following-sibling::td[1]",
            # "//td[contains(text(), 'Inviter')]/following-sibling::td[1]",
            
            # 表格行匹配（当列属性不明确时）
            # "//tr[contains(., '邀请人')]//td[position()>1]",
            # "//tr[contains(., 'Inviter')]//td[position()>1]",
            
            # 中文变体（上家、上级、推荐人）
            # "//td[@class='rowhead' and contains(text(), '上家')]/following-sibling::td[1]",
            # "//td[@class='rowhead' and contains(text(), '上级')]/following-sibling::td[1]",
            # "//td[@class='rowhead' and contains(text(), '推荐人')]/following-sibling::td[1]",
            # "//tr[contains(., '上家')]//td[position()>1]",
            # "//tr[contains(., '上级')]//td[position()>1]",
            # "//tr[contains(., '推荐人')]//td[position()>1]",
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

            # 查找页面中所有包含邀请人相关关键词的元素
            import re
            inviter_keywords = [
                # 中文关键词
                "邀请人"
                # , "上家", "上级", "推荐人", "注册来源", "注册方式", "邀请来源", "邀请我的人", "邀请人信息",
                # "邀请人资料", "邀请人ID", "我的邀请人", "注册介绍人", "介绍人", "介绍我的人", "邀请者", "引荐人",
                # "邀请码来源", "注册邀请人", "邀请人姓名", "邀请人账号", "邀请人用户名", "邀请人昵称", "上家信息",
                # "上级信息", "推荐人信息", "推荐人ID", "引荐人信息", "引荐人ID",
                # 英文关键词
                # "Inviter", "Referrer", "Sponsor", "Invited By", "Invited by", "Who Invited Me", "Registration Source",
                # "Registration Referrer", "Referral Source", "Referral", "Sponsored By", "Sponsored by", "Inviter Info",
                # "Inviter Details", "Inviter ID", "My Inviter", "Referral ID", "Sponsor ID", "Referrer ID"
            ]
            matches = []
            for keyword in inviter_keywords:
                # 使用正则表达式查找包含关键词的文本片段
                keyword_matches = re.finditer(f'.{{0,50}}{re.escape(keyword)}.{{0,100}}', html_content, re.IGNORECASE)
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
            logger.debug(f"  - 页面长度: {len(html_content)} 字符")
            logger.debug(f"  - 是否包含userdetails.php: {'userdetails.php' in html_content}")
            logger.debug(f"  - 是否包含userinfo: {'userinfo' in html_content}")
            logger.debug(f"  - 是否包含profile: {'profile' in html_content}")
            logger.debug(f"  - 是否包含table标签: {'<table' in html_content}")
            logger.debug(f"  - 是否包含ul/ol标签: {'<ul' in html_content or '<ol' in html_content}")
            logger.debug(f"  - 是否包含div标签: {'<div' in html_content}")
            logger.debug(f"  - 是否包含span标签: {'<span' in html_content}")
            
            # 移除了AFUN站点的特殊处理，使用通用的NexusPHP表格结构XPath即可

            logger.info("NexusPHP未找到邀请人信息，返回'无'")
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
            ("邀请人：", "邀请人:", "邀请人")
            # ("Inviter：", "Inviter:", "Inviter"),
            # ("上家：", "上家:", "上家"),
            # ("上级：", "上级:", "上级"),
            # ("推荐人：", "推荐人:", "推荐人"),
            # ("Referrer：", "Referrer:", "Referrer"),
            # ("Sponsor：", "Sponsor:", "Sponsor"),
            # ("邀请人信息：", "邀请人信息:", "邀请人信息"),
            # ("邀请人资料：", "邀请人资料:", "邀请人资料"),
            # ("邀请我的人：", "邀请我的人:", "邀请我的人"),
            # ("Inviter Info：", "Inviter Info:", "Inviter Info"),
            # ("Inviter Details：", "Inviter Details:", "Inviter Details"),
            # ("Who Invited Me：", "Who Invited Me:", "Who Invited Me")
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
            # "//td[@class='rowhead' and text()='邮箱']/following-sibling::td[1]//a/@href",
            # "//td[text()='邮箱']/following-sibling::td[1]//a/@href",
            # "//td[@class='rowhead' and contains(text(), '邮箱')]/following-sibling::td[1]//a/@href",
            # 表格结构 - 直接提取文本
            # "//td[text()='邮箱']/following-sibling::td[1]/text()",
            # "//td[@class='rowhead' and contains(text(), '邮箱')]/following-sibling::td[1]/text()",
            # 列表结构 - 从链接中提取
            # "//div[@class='userinfo']//li[contains(text(), '邮箱')]//a/@href",
            # "//div[@class='profile']//li[contains(text(), '邮箱')]//a/@href",
            # "//div[@id='outer']//li[contains(text(), '邮箱')]//a/@href",
            #"//li[contains(text(), '邮箱')]//a/@href",
            # 列表结构 - 直接提取文本
            # "//div[@class='userinfo']//li[contains(text(), '邮箱')]/text()",
            # "//div[@class='profile']//li[contains(text(), '邮箱')]/text()",
            # "//div[@id='outer']//li[contains(text(), '邮箱')]/text()",
            # "//li[contains(text(), '邮箱')]/text()",
            # "//*[contains(text(), '邮箱')]/following-sibling::*/text()"
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
