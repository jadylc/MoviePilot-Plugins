"""
模块加载器模块
"""
import os
import importlib
import inspect
from typing import List, Type, Dict, Any

from app.log import logger
from app.plugins.inviterinfo.sites import _IInviterInfoHandler


class ModuleLoader:
    """
    模块加载器类
    """
    
    @staticmethod
    def load_site_handlers() -> List[Type[_IInviterInfoHandler]]:
        """
        加载所有站点处理器类
        :return: 站点处理器类列表
        """
        handlers = []
        sites_dir = os.path.join(os.path.dirname(__file__), "sites")
        
        if not os.path.exists(sites_dir):
            logger.error("站点处理器目录不存在: %s", sites_dir)
            return []
        
        logger.info("开始加载站点处理器，扫描目录: %s", sites_dir)
        
        # 遍历sites目录下的所有py文件
        try:
            for filename in os.listdir(sites_dir):
                if not filename.endswith(".py") or filename == "__init__.py":
                    logger.debug("跳过文件: %s", filename)
                    continue
                
                module_name = filename[:-3]  # 去掉.py后缀
                
                try:
                    # 动态导入模块
                    logger.debug("尝试导入模块: %s", module_name)
                    module = importlib.import_module(f"app.plugins.inviterinfo.sites.{module_name}")
                    logger.debug("成功导入模块: %s", module_name)
                    
                    # 查找模块中继承了_IInviterInfoHandler的类
                    try:
                        for name, obj in inspect.getmembers(module):
                            if (inspect.isclass(obj) and 
                                issubclass(obj, _IInviterInfoHandler) and 
                                obj != _IInviterInfoHandler):
                                handlers.append(obj)
                                logger.info(f"加载站点处理器: {obj.__name__}")
                    except Exception as inspect_ex:
                        logger.error("扫描模块 %s 中的处理器类失败: %s", module_name, str(inspect_ex))
                        import traceback
                        logger.error("错误堆栈: %s", traceback.format_exc())
                
                except ImportError as import_ex:
                    logger.error("导入站点处理器模块 %s 失败: %s", module_name, str(import_ex))
                    import traceback
                    logger.error("错误堆栈: %s", traceback.format_exc())
                except Exception as e:
                    logger.error("加载站点处理器模块 %s 失败: %s", module_name, str(e))
                    import traceback
                    logger.error("错误堆栈: %s", traceback.format_exc())
        except Exception as dir_ex:
            logger.error("遍历站点处理器目录失败: %s", str(dir_ex))
            import traceback
            logger.error("错误堆栈: %s", traceback.format_exc())
        
        logger.info("站点处理器加载完成，共加载 %d 个处理器", len(handlers))
        return handlers
    
    @staticmethod
    def get_handler_for_site(site_url: str, handlers: List[Type[_IInviterInfoHandler]]) -> _IInviterInfoHandler:
        """
        获取匹配站点的处理器实例
        :param site_url: 站点URL
        :param handlers: 处理器类列表
        :return: 处理器实例
        """
        if not site_url:
            logger.error("获取站点处理器失败: 站点URL为空")
            return None
        
        if not handlers:
            logger.error("获取站点处理器失败: 处理器列表为空")
            return None
        
        logger.debug("尝试为站点 %s 查找匹配的处理器，共有 %d 个处理器可用", site_url, len(handlers))
        
        for handler_class in handlers:
            try:
                if handler_class.match(site_url):
                    logger.info("找到匹配的站点处理器: %s 匹配站点 %s", handler_class.__name__, site_url)
                    return handler_class()
                logger.debug("处理器 %s 不匹配站点 %s", handler_class.__name__, site_url)
            except Exception as e:
                logger.error("处理器 %s 的match方法执行失败: %s", handler_class.__name__, str(e))
                import traceback
                logger.error("错误堆栈: %s", traceback.format_exc())
        
        logger.info("未找到匹配站点 %s 的处理器", site_url)
        return None