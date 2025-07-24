"""
文件工具模块
包含文件验证、目录创建、文件格式检查等功能
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
from loguru import logger


def validate_input_file(file_path: str) -> bool:
    """
    验证输入文件是否存在且格式支持
    
    Args:
        file_path: 文件路径
        
    Returns:
        是否有效
    """
    try:
        path = Path(file_path)
        
        # 检查文件是否存在
        if not path.exists():
            logger.error(f"文件不存在: {file_path}")
            return False
        
        # 检查文件是否为文件而非目录
        if not path.is_file():
            logger.error(f"路径不是文件: {file_path}")
            return False
        
        # 检查文件扩展名
        supported_extensions = {
            '.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv',  # 视频格式
            '.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg'  # 音频格式
        }
        
        if path.suffix.lower() not in supported_extensions:
            logger.error(f"不支持的文件格式: {path.suffix}")
            return False
        
        # 检查文件大小
        file_size = path.stat().st_size
        max_size = 500 * 1024 * 1024  # 500MB限制
        
        if file_size > max_size:
            logger.error(f"文件过大: {file_size / 1024 / 1024:.2f}MB，限制: {max_size / 1024 / 1024}MB")
            return False
        
        logger.info(f"文件验证通过: {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"文件验证失败: {str(e)}")
        return False


def create_output_dir(output_path: str) -> bool:
    """
    创建输出目录
    
    Args:
        output_path: 输出路径
        
    Returns:
        是否成功创建
    """
    try:
        path = Path(output_path)
        
        # 如果路径是文件，获取其父目录
        if path.suffix:
            path = path.parent
        
        # 创建目录
        path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"输出目录创建成功: {path}")
        return True
        
    except Exception as e:
        logger.error(f"创建输出目录失败: {str(e)}")
        return False


def get_file_info(file_path: str) -> dict:
    """
    获取文件信息
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件信息字典
    """
    try:
        path = Path(file_path)
        
        if not path.exists():
            return {}
        
        stat = path.stat()
        
        return {
            'name': path.name,
            'stem': path.stem,
            'suffix': path.suffix,
            'size': stat.st_size,
            'size_kb': stat.st_size / 1024,
            'size_mb': stat.st_size / 1024 / 1024,
            'created': stat.st_ctime,
            'modified': stat.st_mtime,
            'absolute_path': str(path.absolute()),
            'is_video': path.suffix.lower() in {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'},
            'is_audio': path.suffix.lower() in {'.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg'},
            'is_subtitle': path.suffix.lower() in {'.srt', '.vtt', '.ass'}
        }
        
    except Exception as e:
        logger.error(f"获取文件信息失败: {str(e)}")
        return {}


def clean_filename(filename: str) -> str:
    """
    清理文件名，移除非法字符
    
    Args:
        filename: 原始文件名
        
    Returns:
        清理后的文件名
    """
    # 非法字符列表
    illegal_chars = '<>:"/\\|?*'
    
    # 替换非法字符
    cleaned = filename
    for char in illegal_chars:
        cleaned = cleaned.replace(char, '_')
    
    # 移除多余的空格和点
    cleaned = cleaned.strip()
    cleaned = cleaned.replace('..', '.')
    
    # 确保不为空
    if not cleaned:
        cleaned = 'unnamed_file'
    
    return cleaned


def backup_file(file_path: str, backup_dir: str = None) -> Optional[str]:
    """
    备份文件
    
    Args:
        file_path: 要备份的文件路径
        backup_dir: 备份目录，如果为None则在原目录创建备份
        
    Returns:
        备份文件路径，失败返回None
    """
    try:
        source_path = Path(file_path)
        
        if not source_path.exists():
            logger.error(f"源文件不存在: {file_path}")
            return None
        
        # 确定备份目录
        if backup_dir:
            backup_path = Path(backup_dir)
            backup_path.mkdir(parents=True, exist_ok=True)
        else:
            backup_path = source_path.parent
        
        # 生成备份文件名
        backup_filename = f"{source_path.stem}_backup{source_path.suffix}"
        backup_file_path = backup_path / backup_filename
        
        # 如果备份文件已存在，添加数字后缀
        counter = 1
        while backup_file_path.exists():
            backup_filename = f"{source_path.stem}_backup_{counter}{source_path.suffix}"
            backup_file_path = backup_path / backup_filename
            counter += 1
        
        # 复制文件
        shutil.copy2(source_path, backup_file_path)
        
        logger.info(f"文件备份成功: {backup_file_path}")
        return str(backup_file_path)
        
    except Exception as e:
        logger.error(f"备份文件失败: {str(e)}")
        return None


def get_temp_dir(prefix: str = "ai_dubbing") -> str:
    """
    获取临时目录
    
    Args:
        prefix: 目录前缀
        
    Returns:
        临时目录路径
    """
    import tempfile
    
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"{prefix}_")
        logger.info(f"临时目录创建成功: {temp_dir}")
        return temp_dir
        
    except Exception as e:
        logger.error(f"创建临时目录失败: {str(e)}")
        return tempfile.gettempdir()


def cleanup_temp_files(temp_dir: str) -> bool:
    """
    清理临时文件
    
    Args:
        temp_dir: 临时目录路径
        
    Returns:
        是否成功清理
    """
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"临时文件清理成功: {temp_dir}")
            return True
        return True
        
    except Exception as e:
        logger.error(f"清理临时文件失败: {str(e)}")
        return False


def find_files_by_extension(directory: str, extensions: List[str]) -> List[str]:
    """
    根据扩展名查找文件
    
    Args:
        directory: 搜索目录
        extensions: 扩展名列表
        
    Returns:
        文件路径列表
    """
    try:
        directory_path = Path(directory)
        
        if not directory_path.exists():
            logger.error(f"目录不存在: {directory}")
            return []
        
        files = []
        for ext in extensions:
            pattern = f"*{ext}" if ext.startswith('.') else f"*.{ext}"
            files.extend(directory_path.glob(pattern))
        
        # 转换为字符串路径并排序
        file_paths = [str(f) for f in files]
        file_paths.sort()
        
        logger.info(f"找到 {len(file_paths)} 个文件")
        return file_paths
        
    except Exception as e:
        logger.error(f"查找文件失败: {str(e)}")
        return []


def ensure_directory_exists(path: str) -> bool:
    """
    确保目录存在
    
    Args:
        path: 目录路径
        
    Returns:
        是否成功
    """
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"创建目录失败: {str(e)}")
        return False


def get_available_filename(base_path: str) -> str:
    """
    获取可用的文件名（如果文件已存在则添加数字后缀）
    
    Args:
        base_path: 基础文件路径
        
    Returns:
        可用的文件路径
    """
    path = Path(base_path)
    
    if not path.exists():
        return base_path
    
    counter = 1
    while True:
        new_path = path.parent / f"{path.stem}_{counter}{path.suffix}"
        if not new_path.exists():
            return str(new_path)
        counter += 1


def get_file_hash(file_path: str) -> Optional[str]:
    """
    获取文件的MD5哈希值
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件的MD5哈希值，失败返回None
    """
    import hashlib
    
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
        
    except Exception as e:
        logger.error(f"计算文件哈希失败: {str(e)}")
        return None 


def select_file_interactive(file_types: List[Tuple[str, str]] = None, title: str = "选择文件") -> Optional[str]:
    """
    交互式文件选择器
    
    Args:
        file_types: 文件类型列表，格式为 [("描述", "*.扩展名"), ...]
        title: 对话框标题
        
    Returns:
        选择的文件路径，取消选择返回None
    """
    try:
        # 尝试使用tkinter文件对话框
        try:
            import tkinter as tk
            from tkinter import filedialog
            
            # 创建tkinter根窗口但不显示
            root = tk.Tk()
            root.withdraw()
            
            # 设置默认文件类型
            if file_types is None:
                file_types = [
                    ("SRT字幕文件", "*.srt"),
                    ("所有文件", "*.*")
                ]
            
            # 显示文件选择对话框
            file_path = filedialog.askopenfilename(
                title=title,
                filetypes=file_types
            )
            
            root.destroy()
            
            if file_path:
                logger.info(f"用户选择了文件: {file_path}")
                return file_path
            else:
                logger.info("用户取消了文件选择")
                return None
                
        except ImportError:
            logger.warning("tkinter不可用，使用命令行文件选择")
            
            # 备用方案：命令行文件选择
            return select_file_commandline()
            
    except Exception as e:
        logger.error(f"文件选择失败: {str(e)}")
        return None


def select_file_commandline() -> Optional[str]:
    """
    命令行文件选择器
    
    Returns:
        选择的文件路径，取消选择返回None
    """
    try:
        print("\n=== 文件选择器 ===")
        print("请选择操作：")
        print("1. 输入文件路径")
        print("2. 浏览当前目录")
        print("3. 取消")
        
        choice = input("请输入选项 (1-3): ").strip()
        
        if choice == "1":
            file_path = input("请输入SRT文件路径: ").strip()
            if file_path:
                # 移除引号
                file_path = file_path.strip('"\'')
                path = Path(file_path)
                if path.exists():
                    return str(path.absolute())
                else:
                    print(f"文件不存在: {file_path}")
                    return select_file_commandline()
            else:
                return None
                
        elif choice == "2":
            return browse_directory_for_srt()
            
        elif choice == "3":
            return None
            
        else:
            print("无效选项，请重新选择")
            return select_file_commandline()
            
    except KeyboardInterrupt:
        print("\n用户取消操作")
        return None
    except Exception as e:
        logger.error(f"命令行文件选择失败: {str(e)}")
        return None


def browse_directory_for_srt(directory: str = None) -> Optional[str]:
    """
    浏览目录选择SRT文件
    
    Args:
        directory: 要浏览的目录，默认为当前目录
        
    Returns:
        选择的文件路径，取消选择返回None
    """
    try:
        if directory is None:
            directory = os.getcwd()
        
        current_dir = Path(directory)
        
        while True:
            print(f"\n当前目录: {current_dir}")
            print("=" * 50)
            
            # 获取目录内容
            items = []
            
            # 添加上级目录选项
            if current_dir.parent != current_dir:
                items.append(("目录", "..", "返回上级目录"))
            
            # 添加子目录
            try:
                for item in current_dir.iterdir():
                    if item.is_dir():
                        items.append(("目录", item.name, f"目录 - {item.name}"))
                    elif item.suffix.lower() == '.srt':
                        items.append(("文件", str(item), f"SRT文件 - {item.name}"))
            except PermissionError:
                print("无权限访问此目录")
                return None
            
            if not items:
                print("目录为空")
                return None
            
            # 显示选项
            print("请选择：")
            for i, (item_type, path, description) in enumerate(items, 1):
                print(f"{i}. {description}")
            
            print("0. 取消")
            
            try:
                choice = input(f"请输入选项 (0-{len(items)}): ").strip()
                
                if choice == "0":
                    return None
                
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(items):
                    item_type, path, description = items[choice_idx]
                    
                    if item_type == "目录":
                        if path == "..":
                            current_dir = current_dir.parent
                        else:
                            current_dir = current_dir / path
                    else:  # 文件
                        return path
                else:
                    print("无效选项")
                    
            except ValueError:
                print("请输入有效数字")
            except KeyboardInterrupt:
                print("\n用户取消操作")
                return None
                
    except Exception as e:
        logger.error(f"目录浏览失败: {str(e)}")
        return None


def validate_srt_file(file_path: str) -> bool:
    """
    验证SRT文件格式
    
    Args:
        file_path: 文件路径
        
    Returns:
        是否为有效的SRT文件
    """
    try:
        path = Path(file_path)
        
        # 检查文件是否存在
        if not path.exists():
            logger.error(f"文件不存在: {file_path}")
            return False
        
        # 检查文件扩展名
        if path.suffix.lower() != '.srt':
            logger.error("目前只支持SRT格式的字幕文件")
            return False
        
        # 检查文件大小
        if path.stat().st_size == 0:
            logger.error("字幕文件为空")
            return False
        
        # 简单验证SRT格式
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read(1000)  # 读取前1000字符
                # 检查是否包含时间戳格式
                if '-->' not in content:
                    logger.error("文件不包含有效的SRT时间戳")
                    return False
        except UnicodeDecodeError:
            try:
                with open(path, 'r', encoding='gbk') as f:
                    content = f.read(1000)
                    if '-->' not in content:
                        logger.error("文件不包含有效的SRT时间戳")
                        return False
            except UnicodeDecodeError:
                logger.error("文件编码格式不支持")
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"验证SRT文件失败: {str(e)}")
        return False 


def get_recent_files(max_files: int = 5) -> List[str]:
    """
    获取最近使用的文件列表
    
    Args:
        max_files: 返回的最大文件数
        
    Returns:
        最近使用的文件路径列表
    """
    try:
        recent_files_path = Path.home() / ".ai_dubbing_recent_files"
        
        if not recent_files_path.exists():
            return []
        
        recent_files = []
        with open(recent_files_path, 'r', encoding='utf-8') as f:
            for line in f:
                file_path = line.strip()
                if file_path and Path(file_path).exists():
                    recent_files.append(file_path)
        
        return recent_files[:max_files]
        
    except Exception as e:
        logger.error(f"获取最近文件失败: {str(e)}")
        return []


def save_recent_file(file_path: str) -> None:
    """
    保存最近使用的文件
    
    Args:
        file_path: 文件路径
    """
    try:
        recent_files_path = Path.home() / ".ai_dubbing_recent_files"
        recent_files = get_recent_files(10)  # 获取最近10个文件
        
        # 如果文件已经在列表中，先移除
        if file_path in recent_files:
            recent_files.remove(file_path)
        
        # 添加到列表开头
        recent_files.insert(0, file_path)
        
        # 保存到文件
        with open(recent_files_path, 'w', encoding='utf-8') as f:
            for file in recent_files:
                f.write(f"{file}\n")
        
    except Exception as e:
        logger.error(f"保存最近文件失败: {str(e)}")


def find_srt_files_in_directory(directory: str = None, max_files: int = 10) -> List[str]:
    """
    在指定目录中查找SRT文件
    
    Args:
        directory: 搜索目录，默认为当前目录
        max_files: 返回的最大文件数
        
    Returns:
        找到的SRT文件路径列表
    """
    try:
        if directory is None:
            directory = os.getcwd()
        
        search_dir = Path(directory)
        if not search_dir.exists():
            return []
        
        srt_files = []
        
        # 搜索当前目录
        for file_path in search_dir.glob("*.srt"):
            if file_path.is_file():
                srt_files.append(str(file_path))
        
        # 搜索子目录（只搜索一级）
        for subdir in search_dir.iterdir():
            if subdir.is_dir() and len(srt_files) < max_files:
                for file_path in subdir.glob("*.srt"):
                    if file_path.is_file():
                        srt_files.append(str(file_path))
        
        return sorted(srt_files)[:max_files]
        
    except Exception as e:
        logger.error(f"搜索SRT文件失败: {str(e)}")
        return []


def select_file_enhanced() -> Optional[str]:
    """
    增强版文件选择器，支持最近文件和智能推荐
    
    Returns:
        选择的文件路径，取消选择返回None
    """
    try:
        print("\n🎬 AI配音系统 - 文件选择器")
        print("=" * 50)
        
        # 获取最近使用的文件
        recent_files = get_recent_files(5)
        
        # 搜索当前目录的SRT文件
        found_files = find_srt_files_in_directory(max_files=5)
        
        options = []
        
        # 添加最近使用的文件
        if recent_files:
            print("📋 最近使用的文件:")
            for i, file_path in enumerate(recent_files):
                file_name = Path(file_path).name
                print(f"  {i+1}. {file_name}")
                options.append(("recent", file_path))
            print()
        
        # 添加当前目录找到的文件
        if found_files:
            print("📁 当前目录找到的SRT文件:")
            start_idx = len(options)
            for i, file_path in enumerate(found_files):
                file_name = Path(file_path).name
                print(f"  {start_idx + i + 1}. {file_name}")
                options.append(("found", file_path))
            print()
        
        # 添加其他选项
        other_options = [
            ("browse", "浏览文件夹"),
            ("input", "手动输入路径"),
            ("cancel", "取消")
        ]
        
        print("🛠️ 其他选项:")
        for i, (key, desc) in enumerate(other_options):
            print(f"  {len(options) + i + 1}. {desc}")
        
        print(f"\n请选择 (1-{len(options) + len(other_options)}): ", end="")
        
        try:
            choice = int(input().strip())
            
            if 1 <= choice <= len(options):
                # 选择了文件
                _, file_path = options[choice - 1]
                if validate_srt_file(file_path):
                    save_recent_file(file_path)
                    return file_path
                else:
                    print("❌ 文件验证失败")
                    return select_file_enhanced()
            
            elif choice == len(options) + 1:
                # 浏览文件夹
                return browse_directory_for_srt()
            
            elif choice == len(options) + 2:
                # 手动输入路径
                file_path = input("请输入SRT文件路径: ").strip().strip('"\'')
                if file_path and validate_srt_file(file_path):
                    save_recent_file(file_path)
                    return file_path
                else:
                    print("❌ 文件路径无效")
                    return select_file_enhanced()
            
            elif choice == len(options) + 3:
                # 取消
                return None
            
            else:
                print("❌ 无效选项")
                return select_file_enhanced()
                
        except ValueError:
            print("❌ 请输入有效数字")
            return select_file_enhanced()
            
    except KeyboardInterrupt:
        print("\n用户取消操作")
        return None
    except Exception as e:
        logger.error(f"增强文件选择失败: {str(e)}")
        return select_file_commandline() 