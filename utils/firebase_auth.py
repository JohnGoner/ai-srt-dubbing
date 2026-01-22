"""
Firebase Authentication 模块
提供用户注册、登录、验证等功能
支持 Email/Password 和 Google 登录
"""

import os
import json
import requests
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from loguru import logger

# Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import auth as admin_auth
    from firebase_admin import credentials
    FIREBASE_ADMIN_AVAILABLE = True
except ImportError:
    FIREBASE_ADMIN_AVAILABLE = False
    logger.warning("Firebase Admin SDK 未安装，请运行: pip install firebase-admin")


class FirebaseAuthManager:
    """
    Firebase Authentication 管理器
    
    支持功能：
    - Email/Password 注册和登录
    - 密码重置
    - 用户验证
    - Token 刷新
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if FirebaseAuthManager._initialized:
            return
        
        self.api_key = None
        self.project_id = None
        self.is_connected = False
        self._token_cache: Dict[str, Dict[str, Any]] = {}  # uid -> {token, expires_at}
    
    def initialize(self, config: Dict[str, Any]) -> bool:
        """
        初始化 Firebase Auth
        
        Args:
            config: 配置字典，包含 firebase.api_key 等
            
        Returns:
            是否初始化成功
        """
        if self.is_connected:
            return True
        
        try:
            firebase_config = config.get('firebase', {})
            
            # 获取 Web API Key（用于 REST API 调用）
            self.api_key = firebase_config.get('api_key', '')
            if not self.api_key:
                self.api_key = os.environ.get('FIREBASE_API_KEY', '')
            
            self.project_id = firebase_config.get('project_id', '')
            
            if not self.api_key:
                logger.error("Firebase API Key 未配置，请设置 firebase.api_key 或环境变量 FIREBASE_API_KEY")
                return False
            
            # 确保 Firebase Admin SDK 已初始化（用于服务端验证）
            if FIREBASE_ADMIN_AVAILABLE:
                try:
                    firebase_admin.get_app()
                except ValueError:
                    # 尝试初始化
                    credentials_path = firebase_config.get('credentials_path', '')
                    if not credentials_path:
                        credentials_path = os.environ.get('FIREBASE_CREDENTIALS', '')
                    
                    if credentials_path and os.path.exists(credentials_path):
                        cred = credentials.Certificate(credentials_path)
                        firebase_admin.initialize_app(cred)
                    else:
                        logger.warning("Firebase Admin SDK 凭证未找到，部分功能可能不可用")
            
            self.is_connected = True
            FirebaseAuthManager._initialized = True
            logger.info(f"Firebase Auth 初始化成功 (Project: {self.project_id})")
            return True
            
        except Exception as e:
            logger.error(f"Firebase Auth 初始化失败: {e}")
            return False
    
    def _firebase_auth_request(self, endpoint: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        发送 Firebase Auth REST API 请求
        
        Args:
            endpoint: API 端点名称
            data: 请求数据
            
        Returns:
            (success, response_data)
        """
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={self.api_key}"
        
        try:
            response = requests.post(url, json=data, timeout=30)
            result = response.json()
            
            if response.ok:
                return True, result
            else:
                error_message = result.get('error', {}).get('message', '未知错误')
                return False, {'error': error_message}
                
        except requests.exceptions.Timeout:
            return False, {'error': '请求超时'}
        except requests.exceptions.RequestException as e:
            return False, {'error': f'网络错误: {str(e)}'}
        except Exception as e:
            return False, {'error': f'请求失败: {str(e)}'}
    
    def register_with_email(self, email: str, password: str, display_name: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        使用邮箱注册新用户
        
        Args:
            email: 邮箱地址
            password: 密码（至少 6 位）
            display_name: 显示名称
            
        Returns:
            (success, message, user_info)
        """
        if not self.is_connected:
            return False, "Firebase Auth 未初始化", None
        
        # 验证密码长度
        if len(password) < 6:
            return False, "密码长度至少为 6 位", None
        
        # 调用注册 API
        success, result = self._firebase_auth_request('signUp', {
            'email': email,
            'password': password,
            'returnSecureToken': True
        })
        
        if not success:
            error = result.get('error', '注册失败')
            error_messages = {
                'EMAIL_EXISTS': '该邮箱已被注册',
                'INVALID_EMAIL': '邮箱格式无效',
                'WEAK_PASSWORD': '密码强度不够',
                'OPERATION_NOT_ALLOWED': '邮箱注册功能未启用'
            }
            return False, error_messages.get(error, error), None
        
        # 更新用户显示名称（如果提供）
        if display_name:
            self._firebase_auth_request('update', {
                'idToken': result.get('idToken'),
                'displayName': display_name
            })
        
        user_info = {
            'uid': result.get('localId'),
            'email': email,
            'display_name': display_name or email.split('@')[0],
            'id_token': result.get('idToken'),
            'refresh_token': result.get('refreshToken'),
            'expires_in': int(result.get('expiresIn', 3600))
        }
        
        logger.info(f"用户注册成功: {email} (UID: {user_info['uid']})")
        return True, "注册成功", user_info
    
    def login_with_email(self, email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        使用邮箱登录
        
        Args:
            email: 邮箱地址
            password: 密码
            
        Returns:
            (success, message, user_info)
        """
        if not self.is_connected:
            return False, "Firebase Auth 未初始化", None
        
        # 调用登录 API
        success, result = self._firebase_auth_request('signInWithPassword', {
            'email': email,
            'password': password,
            'returnSecureToken': True
        })
        
        if not success:
            error = result.get('error', '登录失败')
            error_messages = {
                'EMAIL_NOT_FOUND': '用户不存在',
                'INVALID_PASSWORD': '密码错误',
                'INVALID_EMAIL': '邮箱格式无效',
                'USER_DISABLED': '账号已被禁用',
                'TOO_MANY_ATTEMPTS_TRY_LATER': '登录尝试次数过多，请稍后再试',
                'INVALID_LOGIN_CREDENTIALS': '邮箱或密码错误'
            }
            return False, error_messages.get(error, error), None
        
        user_info = {
            'uid': result.get('localId'),
            'email': result.get('email'),
            'display_name': result.get('displayName', email.split('@')[0]),
            'id_token': result.get('idToken'),
            'refresh_token': result.get('refreshToken'),
            'expires_in': int(result.get('expiresIn', 3600)),
            'email_verified': result.get('emailVerified', False)
        }
        
        # 缓存 token
        self._cache_token(user_info['uid'], user_info['id_token'], user_info['expires_in'])
        
        # 记录登录活动日志
        try:
            from .firebase_activity_logger import get_activity_logger
            activity_logger = get_activity_logger()
            activity_logger.log_login(user_info['uid'], login_method="email")
        except Exception as e:
            logger.debug(f"记录登录日志失败（非关键）: {e}")
        
        logger.info(f"用户登录成功: {email} (UID: {user_info['uid']})")
        return True, "登录成功", user_info
    
    def send_password_reset_email(self, email: str) -> Tuple[bool, str]:
        """
        发送密码重置邮件
        
        Args:
            email: 邮箱地址
            
        Returns:
            (success, message)
        """
        if not self.is_connected:
            return False, "Firebase Auth 未初始化"
        
        success, result = self._firebase_auth_request('sendOobCode', {
            'requestType': 'PASSWORD_RESET',
            'email': email
        })
        
        if not success:
            error = result.get('error', '发送失败')
            error_messages = {
                'EMAIL_NOT_FOUND': '该邮箱未注册',
                'INVALID_EMAIL': '邮箱格式无效'
            }
            return False, error_messages.get(error, error)
        
        logger.info(f"密码重置邮件已发送: {email}")
        return True, "密码重置邮件已发送，请检查您的邮箱"
    
    def refresh_token(self, refresh_token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        刷新 ID Token
        
        Args:
            refresh_token: 刷新令牌
            
        Returns:
            (success, new_tokens)
        """
        url = f"https://securetoken.googleapis.com/v1/token?key={self.api_key}"
        
        try:
            response = requests.post(url, data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }, timeout=30)
            
            if response.ok:
                result = response.json()
                return True, {
                    'id_token': result.get('id_token'),
                    'refresh_token': result.get('refresh_token'),
                    'expires_in': int(result.get('expires_in', 3600)),
                    'uid': result.get('user_id')
                }
            else:
                return False, None
                
        except Exception as e:
            logger.error(f"刷新 Token 失败: {e}")
            return False, None
    
    def verify_id_token(self, id_token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        验证 ID Token（服务端验证）
        
        Args:
            id_token: Firebase ID Token
            
        Returns:
            (valid, decoded_token)
        """
        if not FIREBASE_ADMIN_AVAILABLE:
            logger.warning("Firebase Admin SDK 不可用，无法验证 Token")
            return False, None
        
        try:
            decoded = admin_auth.verify_id_token(id_token)
            return True, decoded
        except admin_auth.InvalidIdTokenError:
            return False, None
        except admin_auth.ExpiredIdTokenError:
            return False, None
        except Exception as e:
            logger.error(f"验证 Token 失败: {e}")
            return False, None
    
    def get_user_info(self, id_token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        获取当前用户信息
        
        Args:
            id_token: Firebase ID Token
            
        Returns:
            (success, user_info)
        """
        success, result = self._firebase_auth_request('lookup', {
            'idToken': id_token
        })
        
        if not success:
            return False, None
        
        users = result.get('users', [])
        if not users:
            return False, None
        
        user = users[0]
        return True, {
            'uid': user.get('localId'),
            'email': user.get('email'),
            'display_name': user.get('displayName', ''),
            'email_verified': user.get('emailVerified', False),
            'created_at': user.get('createdAt'),
            'last_login_at': user.get('lastLoginAt')
        }
    
    def update_profile(self, id_token: str, display_name: str = None, photo_url: str = None) -> Tuple[bool, str]:
        """
        更新用户资料
        
        Args:
            id_token: Firebase ID Token
            display_name: 新的显示名称
            photo_url: 新的头像 URL
            
        Returns:
            (success, message)
        """
        data = {'idToken': id_token}
        
        if display_name:
            data['displayName'] = display_name
        if photo_url:
            data['photoUrl'] = photo_url
        
        success, result = self._firebase_auth_request('update', data)
        
        if success:
            return True, "资料更新成功"
        else:
            return False, result.get('error', '更新失败')
    
    def change_password(self, id_token: str, new_password: str) -> Tuple[bool, str]:
        """
        修改密码
        
        Args:
            id_token: Firebase ID Token
            new_password: 新密码
            
        Returns:
            (success, message)
        """
        if len(new_password) < 6:
            return False, "密码长度至少为 6 位"
        
        success, result = self._firebase_auth_request('update', {
            'idToken': id_token,
            'password': new_password,
            'returnSecureToken': True
        })
        
        if success:
            return True, "密码修改成功"
        else:
            return False, result.get('error', '修改失败')
    
    def delete_account(self, id_token: str) -> Tuple[bool, str]:
        """
        删除账号
        
        Args:
            id_token: Firebase ID Token
            
        Returns:
            (success, message)
        """
        success, result = self._firebase_auth_request('delete', {
            'idToken': id_token
        })
        
        if success:
            logger.info("用户账号已删除")
            return True, "账号已删除"
        else:
            return False, result.get('error', '删除失败')
    
    def _cache_token(self, uid: str, id_token: str, expires_in: int):
        """缓存 Token"""
        self._token_cache[uid] = {
            'token': id_token,
            'expires_at': datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        }
    
    def get_cached_token(self, uid: str) -> Optional[str]:
        """获取缓存的 Token（如果未过期）"""
        cache = self._token_cache.get(uid)
        if cache and cache['expires_at'] > datetime.now(timezone.utc):
            return cache['token']
        return None
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            'initialized': self.is_connected,
            'admin_sdk_available': FIREBASE_ADMIN_AVAILABLE,
            'project_id': self.project_id,
            'api_key_configured': bool(self.api_key),
            'cached_tokens': len(self._token_cache)
        }


# 全局单例
_auth_manager: Optional[FirebaseAuthManager] = None


def get_firebase_auth() -> FirebaseAuthManager:
    """获取 Firebase Auth 管理器单例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = FirebaseAuthManager()
    return _auth_manager


def initialize_firebase_auth(config: Dict[str, Any]) -> bool:
    """初始化 Firebase Auth（便捷函数）"""
    manager = get_firebase_auth()
    return manager.initialize(config)
