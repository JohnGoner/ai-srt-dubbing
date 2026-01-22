"""
Firebase 数据迁移工具
用于将本地项目数据迁移到 Firebase 云端存储
"""

import json
import pickle
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from loguru import logger
from io import BytesIO

from models.project_dto import ProjectDTO
from .project_manager import ProjectManager, get_project_manager
from .firebase_project_manager import FirebaseProjectManager, get_firebase_project_manager
from .firebase_storage import get_storage_manager


class FirebaseMigration:
    """Firebase 数据迁移工具"""
    
    def __init__(self, config: Dict[str, Any], user_id: str):
        """
        初始化迁移工具
        
        Args:
            config: 配置字典
            user_id: 目标用户 ID
        """
        self.config = config
        self.user_id = user_id
        
        # 初始化本地管理器
        self.local_manager = get_project_manager()
        
        # 初始化 Firebase 管理器
        self.firebase_manager = get_firebase_project_manager(user_id, config)
        if not self.firebase_manager.is_initialized:
            raise RuntimeError("Firebase 初始化失败，无法进行迁移")
        
        # 初始化 Storage 管理器
        self.storage_manager = get_storage_manager()
        
        self.migration_log: List[Dict[str, Any]] = []
    
    def analyze_local_projects(self) -> Dict[str, Any]:
        """
        分析本地项目数据
        
        Returns:
            分析结果
        """
        try:
            projects = self.local_manager.list_projects()
            
            total_size = 0
            audio_count = 0
            
            for p in projects:
                total_size += p.get('data_file_size', 0)
            
            # 估算音频大小
            for p in projects:
                project = self.local_manager.load_project(p['id'])
                if project:
                    # 检查各阶段的片段中是否有音频
                    for seg in project.final_segments or project.optimized_segments or []:
                        if isinstance(seg, dict) and seg.get('audio_path') or seg.get('audio_data'):
                            audio_count += 1
            
            return {
                'total_projects': len(projects),
                'total_size_bytes': total_size,
                'total_size_mb': total_size / (1024 * 1024),
                'estimated_audio_files': audio_count,
                'projects': projects
            }
            
        except Exception as e:
            logger.error(f"分析本地项目失败: {e}")
            return {'error': str(e)}
    
    def migrate_project(
        self, 
        project_id: str, 
        include_audio: bool = True,
        delete_local: bool = False
    ) -> Tuple[bool, str]:
        """
        迁移单个项目到 Firebase
        
        Args:
            project_id: 项目 ID
            include_audio: 是否迁移音频文件
            delete_local: 迁移成功后是否删除本地数据
            
        Returns:
            (是否成功, 消息)
        """
        try:
            # 加载本地项目
            project = self.local_manager.load_project(project_id)
            if not project:
                return False, f"项目不存在: {project_id}"
            
            logger.info(f"开始迁移项目: {project.name} (ID: {project_id})")
            
            # 设置 Firebase 相关属性
            project.set_owner(self.user_id)
            project.storage_backend = "firebase"
            
            # 迁移音频文件
            audio_migrated = 0
            if include_audio and self.storage_manager and self.storage_manager.is_connected:
                audio_migrated = self._migrate_project_audio(project)
            
            # 保存到 Firebase
            if self.firebase_manager.save_project(project):
                message = f"项目迁移成功: {project.name}, 音频文件: {audio_migrated} 个"
                logger.info(message)
                
                # 记录迁移日志
                self.migration_log.append({
                    'project_id': project_id,
                    'project_name': project.name,
                    'status': 'success',
                    'audio_migrated': audio_migrated,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                
                # 删除本地数据
                if delete_local:
                    self.local_manager.delete_project(project_id)
                    logger.info(f"已删除本地项目: {project_id}")
                
                return True, message
            else:
                return False, f"保存到 Firebase 失败: {project.name}"
                
        except Exception as e:
            error_msg = f"迁移项目失败: {e}"
            logger.error(error_msg)
            self.migration_log.append({
                'project_id': project_id,
                'status': 'failed',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            return False, error_msg
    
    def _migrate_project_audio(self, project: ProjectDTO) -> int:
        """
        迁移项目的音频文件到 Firebase Storage
        
        Args:
            project: 项目对象
            
        Returns:
            迁移的音频文件数量
        """
        migrated_count = 0
        
        # 获取包含音频的片段
        segments = project.final_segments or project.optimized_segments or []
        
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            
            segment_id = seg.get('id', '')
            audio_data = seg.get('audio_data')
            
            if audio_data and segment_id:
                try:
                    # 上传到 Firebase Storage
                    storage_path = self.storage_manager.upload_audio(
                        user_id=self.user_id,
                        project_id=project.id,
                        filename=f"{segment_id}.mp3",
                        audio_data=audio_data,
                        content_type='audio/mpeg'
                    )
                    
                    if storage_path:
                        # 更新项目的音频路径映射
                        project.update_audio_storage_path(segment_id, storage_path)
                        # 清除原始音频数据（节省空间）
                        seg['audio_data'] = None
                        seg['audio_path'] = storage_path
                        migrated_count += 1
                        logger.debug(f"音频上传成功: {segment_id} -> {storage_path}")
                        
                except Exception as e:
                    logger.warning(f"上传音频失败 [{segment_id}]: {e}")
        
        return migrated_count
    
    def migrate_all_projects(
        self, 
        include_audio: bool = True,
        delete_local: bool = False,
        progress_callback = None
    ) -> Dict[str, Any]:
        """
        迁移所有本地项目到 Firebase
        
        Args:
            include_audio: 是否迁移音频文件
            delete_local: 迁移成功后是否删除本地数据
            progress_callback: 进度回调函数 (current, total, project_name)
            
        Returns:
            迁移结果统计
        """
        try:
            projects = self.local_manager.list_projects()
            total = len(projects)
            success_count = 0
            failed_count = 0
            
            logger.info(f"开始批量迁移 {total} 个项目到 Firebase")
            
            for i, project_info in enumerate(projects):
                project_id = project_info['id']
                project_name = project_info.get('name', project_id)
                
                if progress_callback:
                    progress_callback(i + 1, total, project_name)
                
                success, message = self.migrate_project(
                    project_id, 
                    include_audio=include_audio,
                    delete_local=delete_local
                )
                
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"迁移失败: {message}")
            
            result = {
                'total': total,
                'success': success_count,
                'failed': failed_count,
                'migration_log': self.migration_log,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"批量迁移完成: 成功 {success_count}/{total}, 失败 {failed_count}")
            return result
            
        except Exception as e:
            logger.error(f"批量迁移失败: {e}")
            return {'error': str(e)}
    
    def export_migration_report(self, output_path: Optional[str] = None) -> str:
        """
        导出迁移报告
        
        Args:
            output_path: 输出路径，为空则返回 JSON 字符串
            
        Returns:
            报告内容或文件路径
        """
        report = {
            'migration_date': datetime.now(timezone.utc).isoformat(),
            'target_user': self.user_id,
            'total_operations': len(self.migration_log),
            'success_count': sum(1 for log in self.migration_log if log.get('status') == 'success'),
            'failed_count': sum(1 for log in self.migration_log if log.get('status') == 'failed'),
            'details': self.migration_log
        }
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            return output_path
        else:
            return json.dumps(report, ensure_ascii=False, indent=2)


def run_migration_wizard(config: Dict[str, Any], user_id: str):
    """
    运行迁移向导（命令行）
    
    Args:
        config: 配置字典
        user_id: 目标用户 ID
    """
    print("\n" + "=" * 50)
    print("  Firebase 数据迁移向导")
    print("=" * 50 + "\n")
    
    try:
        migration = FirebaseMigration(config, user_id)
        
        # 分析本地数据
        print("正在分析本地数据...")
        analysis = migration.analyze_local_projects()
        
        if 'error' in analysis:
            print(f"分析失败: {analysis['error']}")
            return
        
        print(f"\n本地项目统计:")
        print(f"  - 项目数量: {analysis['total_projects']}")
        print(f"  - 总大小: {analysis['total_size_mb']:.2f} MB")
        print(f"  - 估计音频文件: {analysis['estimated_audio_files']} 个")
        
        if analysis['total_projects'] == 0:
            print("\n没有可迁移的项目。")
            return
        
        # 确认迁移
        print(f"\n将迁移到用户: {user_id}")
        confirm = input("是否继续迁移？(y/n): ").strip().lower()
        
        if confirm != 'y':
            print("迁移已取消。")
            return
        
        # 是否包含音频
        include_audio = input("是否迁移音频文件？(y/n, 默认 y): ").strip().lower() != 'n'
        
        # 是否删除本地
        delete_local = input("迁移成功后是否删除本地数据？(y/n, 默认 n): ").strip().lower() == 'y'
        
        # 执行迁移
        print("\n开始迁移...")
        
        def progress_callback(current, total, name):
            print(f"  [{current}/{total}] {name}")
        
        result = migration.migrate_all_projects(
            include_audio=include_audio,
            delete_local=delete_local,
            progress_callback=progress_callback
        )
        
        # 显示结果
        print(f"\n迁移完成!")
        print(f"  - 成功: {result.get('success', 0)}")
        print(f"  - 失败: {result.get('failed', 0)}")
        
        # 保存报告
        report_path = Path.cwd() / f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        migration.export_migration_report(str(report_path))
        print(f"\n迁移报告已保存: {report_path}")
        
    except Exception as e:
        print(f"\n迁移过程发生错误: {e}")
        logger.exception("迁移向导执行失败")


if __name__ == "__main__":
    import sys
    
    print("Firebase 数据迁移工具")
    print("-" * 30)
    
    # 从命令行参数或环境变量获取用户 ID
    if len(sys.argv) > 1:
        user_id = sys.argv[1]
    else:
        user_id = input("请输入目标用户 ID: ").strip()
    
    if not user_id:
        print("错误: 用户 ID 不能为空")
        sys.exit(1)
    
    # 加载配置
    from .config_manager import get_global_config_manager
    config_manager = get_global_config_manager()
    config = config_manager.load_config()
    
    if not config:
        print("错误: 无法加载配置文件")
        sys.exit(1)
    
    run_migration_wizard(config, user_id)
