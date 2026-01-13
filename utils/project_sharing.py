"""
工程分享模块
提供工程的URL分享和云端同步功能
"""

import json
import base64
import urllib.parse
from typing import Dict, Any, Optional
from loguru import logger
from datetime import datetime, timezone

from models.project_dto import ProjectDTO
from .project_manager import get_project_manager


class ProjectSharingManager:
    """工程分享管理器"""
    
    def __init__(self):
        """初始化分享管理器"""
        self.project_manager = get_project_manager()
        self.base_url = "https://ai-dubbing.app/shared"  # 示例URL，实际应用中需要配置
    
    def create_share_link(self, project_id: str, expire_days: int = 30) -> Optional[str]:
        """
        创建工程分享链接
        
        Args:
            project_id: 工程ID
            expire_days: 链接有效期（天）
            
        Returns:
            分享链接URL
        """
        try:
            project = self.project_manager.load_project(project_id)
            if not project:
                logger.error(f"工程不存在: {project_id}")
                return None
            
            # 创建分享数据
            share_data = self._create_share_data(project, expire_days)
            
            # 编码分享数据
            encoded_data = self._encode_share_data(share_data)
            
            # 生成分享URL
            share_url = f"{self.base_url}?data={encoded_data}"
            
            # 更新工程的分享信息
            project.set_share_info(share_url)
            self.project_manager.save_project(project)
            
            logger.info(f"创建分享链接成功: {project.name}")
            return share_url
            
        except Exception as e:
            logger.error(f"创建分享链接失败: {e}")
            return None
    
    def parse_share_link(self, share_url: str) -> Optional[Dict[str, Any]]:
        """
        解析分享链接
        
        Args:
            share_url: 分享链接
            
        Returns:
            解析的工程数据
        """
        try:
            # 提取数据参数
            parsed_url = urllib.parse.urlparse(share_url)
            params = urllib.parse.parse_qs(parsed_url.query)
            
            if 'data' not in params:
                logger.error("分享链接格式错误：缺少数据参数")
                return None
            
            encoded_data = params['data'][0]
            
            # 解码分享数据
            share_data = self._decode_share_data(encoded_data)
            
            # 验证分享数据
            if not self._validate_share_data(share_data):
                logger.error("分享数据验证失败")
                return None
            
            return share_data
            
        except Exception as e:
            logger.error(f"解析分享链接失败: {e}")
            return None
    
    def import_from_share_link(self, share_url: str, new_name: str = "") -> Optional[ProjectDTO]:
        """
        从分享链接导入工程
        
        Args:
            share_url: 分享链接
            new_name: 新工程名称（可选）
            
        Returns:
            导入的工程对象
        """
        try:
            share_data = self.parse_share_link(share_url)
            if not share_data:
                return None
            
            # 重建工程对象
            project_data = share_data.get('project_data', {})
            project = ProjectDTO.from_dict(project_data)
            
            # 重置工程信息
            project.id = ""  # 重新生成ID
            if new_name:
                project.name = new_name
            else:
                project.name = f"{project.name} - 共享副本"
            
            project.created_at = datetime.now(timezone.utc).isoformat()
            project.updated_at = datetime.now(timezone.utc).isoformat()
            project.is_shared = False
            project.share_url = ""
            project.add_tags(["共享导入"])
            
            # 调用__post_init__重新生成ID和更新统计
            project.__post_init__()
            
            # 保存导入的工程
            if self.project_manager.save_project(project):
                logger.info(f"从分享链接导入工程成功: {project.name}")
                return project
            else:
                return None
                
        except Exception as e:
            logger.error(f"从分享链接导入工程失败: {e}")
            return None
    
    def create_qr_code(self, share_url: str) -> Optional[str]:
        """
        为分享链接创建二维码
        
        Args:
            share_url: 分享链接
            
        Returns:
            二维码图片的base64编码
        """
        try:
            import qrcode  # type: ignore
            from io import BytesIO
            import base64
            
            # 生成二维码
            qr = qrcode.QRCode(version=1, box_size=10, border=5)  # type: ignore
            qr.add_data(share_url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # 转换为base64
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            img_str = base64.b64encode(buffer.getvalue()).decode()
            
            return img_str
            
        except ImportError:
            logger.warning("qrcode库未安装，无法生成二维码")
            return None
        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            return None
    
    def _create_share_data(self, project: ProjectDTO, expire_days: int) -> Dict[str, Any]:
        """创建分享数据"""
        expire_time = datetime.now(timezone.utc).timestamp() + (expire_days * 24 * 3600)
        
        return {
            "version": "1.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expire_time,
            "project_data": project.to_dict(),
            "metadata": {
                "original_id": project.id,
                "share_count": 0,
                "creator": project.created_by or "anonymous"
            }
        }
    
    def _encode_share_data(self, share_data: Dict[str, Any]) -> str:
        """编码分享数据"""
        json_str = json.dumps(share_data, ensure_ascii=False, separators=(',', ':'))
        encoded_bytes = base64.urlsafe_b64encode(json_str.encode('utf-8'))
        return encoded_bytes.decode('ascii')
    
    def _decode_share_data(self, encoded_data: str) -> Dict[str, Any]:
        """解码分享数据"""
        decoded_bytes = base64.urlsafe_b64decode(encoded_data.encode('ascii'))
        json_str = decoded_bytes.decode('utf-8')
        return json.loads(json_str)
    
    def _validate_share_data(self, share_data: Dict[str, Any]) -> bool:
        """验证分享数据"""
        try:
            # 检查版本
            if share_data.get("version") != "1.0":
                logger.error("不支持的分享数据版本")
                return False
            
            # 检查过期时间
            expires_at = share_data.get("expires_at")
            if expires_at and expires_at < datetime.now(timezone.utc).timestamp():
                logger.error("分享链接已过期")
                return False
            
            # 检查工程数据
            project_data = share_data.get("project_data")
            if not project_data or not isinstance(project_data, dict):
                logger.error("分享数据中缺少工程信息")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"验证分享数据时发生错误: {e}")
            return False
    
    def revoke_share(self, project_id: str) -> bool:
        """
        撤销工程分享
        
        Args:
            project_id: 工程ID
            
        Returns:
            是否成功撤销
        """
        try:
            project = self.project_manager.load_project(project_id)
            if not project:
                return False
            
            # 清除分享信息
            project.set_share_info("", "")
            
            # 保存更新
            success = self.project_manager.save_project(project)
            if success:
                logger.info(f"撤销工程分享成功: {project.name}")
            
            return success
            
        except Exception as e:
            logger.error(f"撤销工程分享失败: {e}")
            return False
    
    def get_share_statistics(self, project_id: str) -> Dict[str, Any]:
        """
        获取分享统计信息
        
        Args:
            project_id: 工程ID
            
        Returns:
            分享统计信息
        """
        try:
            project = self.project_manager.load_project(project_id)
            if not project:
                return {}
            
            return {
                "is_shared": project.is_shared,
                "share_url": project.share_url,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
                "share_status": "已分享" if project.is_shared else "未分享"
            }
            
        except Exception as e:
            logger.error(f"获取分享统计失败: {e}")
            return {}


# 全局分享管理器实例
_global_sharing_manager = None


def get_project_sharing_manager() -> ProjectSharingManager:
    """获取全局工程分享管理器实例"""
    global _global_sharing_manager
    if _global_sharing_manager is None:
        _global_sharing_manager = ProjectSharingManager()
    return _global_sharing_manager
