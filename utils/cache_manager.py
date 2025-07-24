"""
本地缓存管理器
管理SRT字幕文件信息、分段信息、翻译信息等的本地缓存
"""

import json
import os
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
import pickle
import tempfile
from datetime import datetime


class LocalCacheManager:
    """本地缓存管理器"""
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录路径，默认为用户主目录下的.ai_dubbing_cache
        """
        if cache_dir is None:
            self.cache_dir = Path.home() / ".ai_dubbing_cache"
        else:
            self.cache_dir = Path(cache_dir)
        
        # 创建缓存目录
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 缓存文件路径
        self.cache_index_file = self.cache_dir / "cache_index.json"
        self.cache_data_dir = self.cache_dir / "data"
        self.cache_data_dir.mkdir(exist_ok=True)
        
        # 加载缓存索引
        self.cache_index = self._load_cache_index()
        
        logger.debug(f"缓存管理器初始化完成: {self.cache_dir}")

    def get_cache_key_for_text(self, cache_type: str, text: str, **kwargs) -> str:
        """
        为纯文本内容生成缓存键。
        
        Args:
            cache_type: 缓存类型
            text: 文本内容
            **kwargs: 其他区分参数 (如 target_language)
            
        Returns:
            缓存键 (MD5哈希)
        """
        key_parts = [cache_type, text]
        for key, value in sorted(kwargs.items()):
            key_parts.append(f"{key}={value}")
        
        key_content = "_".join(key_parts)
        return hashlib.md5(key_content.encode('utf-8')).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """
        根据键获取通用缓存数据。
        
        Args:
            key: 缓存键 (通过get_cache_key_for_text生成)
            
        Returns:
            缓存的数据，或None
        """
        entry = self.cache_index["cache_entries"].get(key)
        if not entry:
            return None

        cache_file = self.cache_data_dir / f"{key}.pkl"
        if not cache_file.exists():
            logger.warning(f"缓存索引存在但数据文件丢失: {key}")
            self._remove_cache_entry(key)
            return None
            
        try:
            with open(cache_file, 'rb') as f:
                cached_data = pickle.load(f)
            
            entry["last_accessed"] = datetime.now().isoformat()
            entry["access_count"] += 1
            self._save_cache_index()
            
            logger.debug(f"通用缓存命中: {key[:10]}... ({entry['cache_type']})")
            return cached_data
        except Exception as e:
            logger.error(f"获取通用缓存失败: {e}")
            return None

    def set(self, key: str, data: Any, cache_type: str, **kwargs):
        """
        根据键设置通用缓存数据。
        
        Args:
            key: 缓存键
            data: 要缓存的数据
            cache_type: 缓存类型
            **kwargs: 用于存储的元信息
        """
        try:
            entry_info = {
                "cache_key": key,
                "cache_type": cache_type,
                "created_at": datetime.now().isoformat(),
                "last_accessed": datetime.now().isoformat(),
                "access_count": 1,
                "extra_params": kwargs,
                "is_generic": True # 标记为通用缓存
            }
            
            cache_file = self.cache_data_dir / f"{key}.pkl"
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            
            self.cache_index["cache_entries"][key] = entry_info
            # ... (此处省略了更新statistics的代码，可以后续添加)
            self._save_cache_index()
            logger.debug(f"通用缓存已保存: {key[:10]}... ({cache_type})")
        except Exception as e:
            logger.error(f"设置通用缓存失败: {e}")
    
    def _load_cache_index(self) -> Dict[str, Any]:
        """加载缓存索引"""
        try:
            if self.cache_index_file.exists():
                with open(self.cache_index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return {
                    "version": "1.0",
                    "created_at": datetime.now().isoformat(),
                    "cache_entries": {},
                    "statistics": {
                        "total_entries": 0,
                        "total_size": 0,
                        "last_cleanup": None
                    }
                }
        except Exception as e:
            logger.warning(f"加载缓存索引失败: {e}")
            return {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "cache_entries": {},
                "statistics": {
                    "total_entries": 0,
                    "total_size": 0,
                    "last_cleanup": None
                }
            }
    
    def _save_cache_index(self):
        """保存缓存索引"""
        try:
            with open(self.cache_index_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存索引失败: {e}")
    
    def _get_file_hash(self, file_path: str) -> str:
        """获取文件的MD5哈希值"""
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logger.error(f"计算文件哈希失败: {e}")
            return ""
    
    def _get_cache_key(self, file_path: str, cache_type: str, **kwargs) -> str:
        """生成缓存键"""
        # 基础信息
        file_hash = self._get_file_hash(file_path)
        file_info = Path(file_path)
        
        # 构建键值
        key_parts = [
            file_hash,
            cache_type,
            file_info.name,
            str(file_info.stat().st_size) if file_info.exists() else "0"
        ]
        
        # 添加额外参数
        for key, value in sorted(kwargs.items()):
            key_parts.append(f"{key}={value}")
        
        # 生成最终键
        key_content = "_".join(key_parts)
        return hashlib.md5(key_content.encode('utf-8')).hexdigest()
    
    def get_cache_entry(self, file_path: str, cache_type: str, skip_validation: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
        """
        获取缓存项
        
        Args:
            file_path: 文件路径
            cache_type: 缓存类型
            skip_validation: 是否跳过缓存有效性验证
            **kwargs: 其他缓存标识参数
            
        Returns:
            缓存的数据，如果不存在或已过期则返回None
        """
        
        try:
            cache_key = self._get_cache_key(file_path, cache_type, **kwargs)
            
            if cache_key not in self.cache_index["cache_entries"]:
                return None
            
            entry = self.cache_index["cache_entries"][cache_key]
            
            # 检查文件是否仍然存在且未修改
            if not skip_validation and not self._is_cache_valid(entry, file_path):
                logger.debug(f"缓存已过期: {cache_key}")
                self._remove_cache_entry(cache_key)
                return None
            
            # 加载缓存数据
            cache_file = self.cache_data_dir / f"{cache_key}.pkl"
            if not cache_file.exists():
                logger.warning(f"缓存数据文件不存在: {cache_file}")
                self._remove_cache_entry(cache_key)
                return None
            
            with open(cache_file, 'rb') as f:
                cached_data = pickle.load(f)
            
            # 更新访问时间
            entry["last_accessed"] = datetime.now().isoformat()
            entry["access_count"] += 1
            self._save_cache_index()
            
            logger.debug(f"缓存命中: {cache_type} for {Path(file_path).name}")
            return cached_data
            
        except Exception as e:
            logger.error(f"获取缓存失败: {e}")
            return None
    
    def save_cache_entry(self, file_path: str, cache_type: str, data: Dict[str, Any], **kwargs) -> bool:
        """
        保存缓存项
        
        Args:
            file_path: 文件路径
            cache_type: 缓存类型 
            data: 要缓存的数据
            **kwargs: 其他缓存标识参数
            
        Returns:
            是否保存成功
        """
        try:
            cache_key = self._get_cache_key(file_path, cache_type, **kwargs)
            
            # 保存数据文件
            cache_file = self.cache_data_dir / f"{cache_key}.pkl"
            with open(cache_file, 'wb') as f:
                pickle.dump(data, f)
            
            # 更新索引
            file_stat = os.stat(file_path)
            entry = {
                "cache_key": cache_key,
                "file_path": file_path,
                "cache_type": cache_type,
                "created_at": datetime.now().isoformat(),
                "last_accessed": datetime.now().isoformat(),
                "access_count": 1,
                "file_hash": self._get_file_hash(file_path),
                "file_size": file_stat.st_size,
                "file_mtime": file_stat.st_mtime,
                "data_size": cache_file.stat().st_size,
                **kwargs
            }
            
            self.cache_index["cache_entries"][cache_key] = entry
            self.cache_index["statistics"]["total_entries"] = len(self.cache_index["cache_entries"])
            
            self._save_cache_index()
            
            logger.debug(f"缓存保存成功: {cache_type} for {Path(file_path).name}")
            return True
            
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
            return False
    
    def _is_cache_valid(self, entry: Dict[str, Any], file_path: str) -> bool:
        """检查缓存是否有效"""
        try:
            file_info = Path(file_path)
            
            # 检查文件是否存在
            if not file_info.exists():
                return False
            
            # 检查文件大小是否变化
            if file_info.stat().st_size != entry["file_size"]:
                return False
            
            # 检查文件哈希是否变化
            current_hash = self._get_file_hash(file_path)
            if current_hash != entry["file_hash"]:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"检查缓存有效性失败: {e}")
            return False
    
    def _remove_cache_entry(self, cache_key: str):
        """移除缓存条目"""
        try:
            if cache_key in self.cache_index["cache_entries"]:
                # 删除数据文件
                cache_file = self.cache_data_dir / f"{cache_key}.pkl"
                if cache_file.exists():
                    cache_file.unlink()
                
                # 从索引中移除
                del self.cache_index["cache_entries"][cache_key]
                self._save_cache_index()
                
                logger.info(f"缓存条目已移除: {cache_key}")
                
        except Exception as e:
            logger.error(f"移除缓存条目失败: {e}")
    
    def clear_cache(self, cache_type: Optional[str] = None):
        """
        清理缓存
        
        Args:
            cache_type: 要清理的缓存类型，如果为None则清理所有缓存
        """
        try:
            keys_to_remove = []
            
            for cache_key, entry in self.cache_index["cache_entries"].items():
                if cache_type is None or entry["cache_type"] == cache_type:
                    keys_to_remove.append(cache_key)
            
            for cache_key in keys_to_remove:
                self._remove_cache_entry(cache_key)
            
            logger.info(f"缓存清理完成: 移除了 {len(keys_to_remove)} 个条目")
            
        except Exception as e:
            logger.error(f"清理缓存失败: {e}")
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            stats = self.cache_index["statistics"].copy()
            
            # 按类型统计
            type_stats = {}
            for entry in self.cache_index["cache_entries"].values():
                cache_type = entry["cache_type"]
                if cache_type not in type_stats:
                    type_stats[cache_type] = {"count": 0, "total_size": 0}
                type_stats[cache_type]["count"] += 1
                
                # 计算文件大小
                cache_file = self.cache_data_dir / f"{entry['cache_key']}.pkl"
                if cache_file.exists():
                    type_stats[cache_type]["total_size"] += cache_file.stat().st_size
            
            stats["type_statistics"] = type_stats
            
            # 计算缓存目录总大小
            total_size = 0
            for file_path in self.cache_data_dir.glob("*.pkl"):
                total_size += file_path.stat().st_size
            
            stats["cache_directory_size"] = total_size
            stats["cache_directory_size_mb"] = total_size / (1024 * 1024)
            
            return stats
            
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}")
            return {}
    
    def find_related_caches(self, file_path: str) -> List[Dict[str, Any]]:
        """
        查找与指定文件相关的所有缓存
        
        Args:
            file_path: 文件路径
            
        Returns:
            相关缓存条目列表
        """
        try:
            file_hash = self._get_file_hash(file_path)
            related_caches = []
            
            for entry in self.cache_index["cache_entries"].values():
                if entry["file_hash"] == file_hash:
                    related_caches.append(entry)
            
            return sorted(related_caches, key=lambda x: x["created_at"], reverse=True)
            
        except Exception as e:
            logger.error(f"查找相关缓存失败: {e}")
            return []
    
    def cleanup_old_cache(self, max_age_days: int = 30, max_size_mb: int = 500):
        """
        清理过期和过大的缓存
        
        Args:
            max_age_days: 最大保留天数
            max_size_mb: 最大缓存大小（MB）
        """
        try:
            current_time = datetime.now()
            max_age_seconds = max_age_days * 24 * 3600
            max_size_bytes = max_size_mb * 1024 * 1024
            
            # 获取当前缓存大小
            current_size = 0
            cache_files = []
            
            for cache_key, entry in self.cache_index["cache_entries"].items():
                cache_file = self.cache_data_dir / f"{cache_key}.pkl"
                if cache_file.exists():
                    file_size = cache_file.stat().st_size
                    current_size += file_size
                    
                    # 检查文件年龄
                    created_time = datetime.fromisoformat(entry["created_at"])
                    age_seconds = (current_time - created_time).total_seconds()
                    
                    cache_files.append({
                        "cache_key": cache_key,
                        "file_size": file_size,
                        "age_seconds": age_seconds,
                        "access_count": entry["access_count"]
                    })
            
            # 按访问次数和年龄排序（最少访问且最老的排在前面）
            cache_files.sort(key=lambda x: (x["access_count"], x["age_seconds"]))
            
            # 清理过期的缓存
            removed_count = 0
            for cache_file_info in cache_files:
                if cache_file_info["age_seconds"] > max_age_seconds:
                    self._remove_cache_entry(cache_file_info["cache_key"])
                    removed_count += 1
            
            # 如果仍然超过大小限制，继续清理
            if current_size > max_size_bytes:
                for cache_file_info in cache_files:
                    if cache_file_info["cache_key"] in self.cache_index["cache_entries"]:
                        self._remove_cache_entry(cache_file_info["cache_key"])
                        removed_count += 1
                        
                        # 重新计算大小
                        current_size = sum(
                            Path(self.cache_data_dir / f"{k}.pkl").stat().st_size 
                            for k in self.cache_index["cache_entries"].keys()
                            if (self.cache_data_dir / f"{k}.pkl").exists()
                        )
                        
                        if current_size <= max_size_bytes:
                            break
            
            # 更新清理时间
            self.cache_index["statistics"]["last_cleanup"] = current_time.isoformat()
            self._save_cache_index()
            
            logger.info(f"缓存清理完成: 移除了 {removed_count} 个条目")
            
        except Exception as e:
            logger.error(f"清理过期缓存失败: {e}")


# 全局缓存管理器实例
global_cache_manager = LocalCacheManager()


def get_cache_manager() -> LocalCacheManager:
    """获取全局缓存管理器实例"""
    return global_cache_manager 