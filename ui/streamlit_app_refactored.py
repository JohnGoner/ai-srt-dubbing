"""
重构后的Streamlit应用 - 纯状态机调度器
只负责状态管理和session_state存取，不直接画UI
"""

import streamlit as st
import os
import tempfile
from pathlib import Path
import sys
from loguru import logger
from typing import Dict, Any
import hashlib
import time

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).parent.parent))


def _setup_network_config():
    """
    设置网络配置（代理绕过等）
    在应用启动时调用，仅执行一次
    """
    if st.session_state.get('_network_configured', False):
        return
    
    try:
        from utils.config_manager import get_global_config_manager
        config_manager = get_global_config_manager()
        config = config_manager.load_config()
        
        if config:
            network_config = config.get('network', {})
            bypass_proxy = network_config.get('bypass_proxy', False)
            
            if bypass_proxy:
                # 清除代理环境变量，让 requests/urllib 直连
                proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                             'NO_PROXY', 'no_proxy', 'ALL_PROXY', 'all_proxy']
                for var in proxy_vars:
                    if var in os.environ:
                        del os.environ[var]
                
                # 设置 NO_PROXY 为 * 以确保所有请求直连
                os.environ['NO_PROXY'] = '*'
                os.environ['no_proxy'] = '*'
                
                logger.info("已启用代理绕过模式，Firebase Storage 将使用直连")
        
        st.session_state['_network_configured'] = True
        
    except Exception as e:
        logger.warning(f"设置网络配置失败: {e}")

from models.segment_dto import SegmentDTO
from models.project_dto import ProjectDTO
from ui.workflow import WorkflowManager
from ui.components.project_management_view import ProjectManagementView
from utils.config_manager import ConfigManager
from utils.file_utils import get_file_info, validate_srt_file
from utils.logger_config import setup_logging
from utils.project_integration import get_project_integration


def get_current_user_id() -> str:
    """
    获取当前登录用户的 ID（用于 Firebase 数据隔离）
    
    对于 Firebase Auth 用户，使用 UID（唯一标识符）
    对于本地配置用户，使用用户名
    
    Returns:
        用户 ID，未登录时返回 'anonymous'
    """
    # 首先检查是否已认证
    if not st.session_state.get('authenticated', False):
        # 未认证状态下，检查是否启用认证
        try:
            from utils.config_manager import get_global_config_manager
            config_manager = get_global_config_manager()
            config = config_manager.load_config()
            security_config = config.get('security', {}) if config else {}
            
            # 如果未启用认证，使用默认用户
            if not security_config.get('enable_auth', False):
                return 'default_user'
        except Exception:
            pass
        
        # 启用认证但未登录，返回 anonymous
        return 'anonymous'
    
    # 已认证用户
    # Firebase Auth 用户：使用 UID
    auth_provider = st.session_state.get('auth_provider')
    if auth_provider == 'firebase':
        # auth_username 在 Firebase 模式下存储的是 UID
        uid = st.session_state.get('auth_username')
        if uid:
            return uid
    
    # 本地配置用户：使用用户名
    auth_username = st.session_state.get('auth_username')
    if auth_username:
        return auth_username
    
    return 'anonymous'


def get_current_display_name() -> str:
    """
    获取当前用户的显示名称
    
    Returns:
        显示名称
    """
    # 首先检查是否已认证
    if not st.session_state.get('authenticated', False):
        return '访客'
    
    display_name = st.session_state.get('auth_display_name')
    if display_name:
        return display_name
    
    auth_username = st.session_state.get('auth_username')
    if auth_username:
        return auth_username
    
    return '访客'


def get_user_project_integration():
    """
    获取当前用户的工程集成实例（自动关联 Firebase 用户 ID）
    
    Returns:
        ProjectIntegration 实例（已关联当前用户）
    """
    user_id = get_current_user_id()
    return get_project_integration(user_id=user_id)


def check_authentication() -> bool:
    """
    检查用户认证状态
    
    Returns:
        bool: 是否已认证
    """
    # 获取安全配置
    try:
        from utils.config_manager import get_global_config_manager
        config_manager = get_global_config_manager()
        config = config_manager.load_config()
        security_config = config.get('security', {}) if config else {}
    except Exception as e:
        logger.warning(f"读取安全配置失败: {e}")
        security_config = {}
    
    # 如果未启用认证，直接返回True
    if not security_config.get('enable_auth', False):
        return True
    
    # 检查session中的认证状态
    if st.session_state.get('authenticated', False):
        # 检查会话是否超时
        auth_time = st.session_state.get('auth_time', 0)
        timeout = security_config.get('session_timeout', 60) * 60  # 转换为秒
        if time.time() - auth_time < timeout:
            return True
        else:
            # 会话已超时
            st.session_state['authenticated'] = False
            username = st.session_state.get('auth_username', 'unknown')
            if security_config.get('log_access', True):
                logger.info(f"会话超时 - 用户: {username}, IP: {_get_client_ip()}")
            st.warning("会话已超时，请重新登录")
    
    return False


def _hash_password(password: str) -> str:
    """计算密码的SHA256哈希值"""
    return hashlib.sha256(password.encode()).hexdigest()


def _check_account_locked(username: str, security_config: dict) -> tuple:
    """
    检查账号是否被锁定
    
    Returns:
        (is_locked, remaining_minutes)
    """
    lockout_key = f'lockout_{username}'
    lockout_until = st.session_state.get(lockout_key, 0)
    
    if lockout_until > time.time():
        remaining = (lockout_until - time.time()) / 60
        return True, remaining
    
    return False, 0


def _record_login_attempt(username: str, success: bool, security_config: dict):
    """
    记录登录尝试
    
    Args:
        username: 用户名
        success: 是否成功
        security_config: 安全配置
    """
    attempts_key = f'login_attempts_{username}'
    lockout_key = f'lockout_{username}'
    
    if success:
        # 登录成功，清除失败计数
        st.session_state[attempts_key] = 0
        if lockout_key in st.session_state:
            del st.session_state[lockout_key]
    else:
        # 登录失败，增加计数
        current_attempts = st.session_state.get(attempts_key, 0) + 1
        st.session_state[attempts_key] = current_attempts
        
        max_attempts = security_config.get('max_login_attempts', 5)
        lockout_duration = security_config.get('lockout_duration', 15)
        
        if current_attempts >= max_attempts:
            # 锁定账号
            st.session_state[lockout_key] = time.time() + (lockout_duration * 60)
            logger.warning(f"账号锁定 - 用户: {username}, 锁定时长: {lockout_duration}分钟, IP: {_get_client_ip()}")


def _verify_user(username: str, password: str, security_config: dict) -> tuple:
    """
    验证用户凭据（本地配置模式）
    
    Returns:
        (success, message, user_info)
    """
    users = security_config.get('users', {})
    
    # 如果没有配置用户，使用旧版单密码模式
    if not users:
        access_password = security_config.get('access_password', '')
        if password == access_password:
            return True, "登录成功", {'role': 'user'}
        else:
            return False, "密码错误", None
    
    # 用户名检查（不区分大小写）
    user_info = None
    actual_username = None
    for u_name, u_info in users.items():
        if u_name.lower() == username.lower():
            user_info = u_info
            actual_username = u_name
            break
    
    if not user_info:
        return False, "用户名不存在", None
    
    # 检查用户是否启用
    if not user_info.get('enabled', True):
        return False, "账号已禁用，请联系管理员", None
    
    # 验证密码哈希
    stored_hash = user_info.get('password_hash', '')
    input_hash = _hash_password(password)
    
    if input_hash == stored_hash:
        return True, "登录成功", {'role': user_info.get('role', 'user'), 'username': actual_username}
    else:
        return False, "密码错误", None


def _verify_user_firebase(email: str, password: str, config: dict) -> tuple:
    """
    使用 Firebase Auth 验证用户
    
    Returns:
        (success, message, user_info)
    """
    try:
        from utils.firebase_auth import get_firebase_auth, initialize_firebase_auth
        
        # 初始化 Firebase Auth
        auth_manager = get_firebase_auth()
        if not auth_manager.is_connected:
            if not initialize_firebase_auth(config):
                return False, "Firebase Auth 初始化失败", None
        
        # 登录
        success, message, user_info = auth_manager.login_with_email(email, password)
        
        if success:
            return True, message, {
                'username': user_info['display_name'],
                'uid': user_info['uid'],
                'email': user_info['email'],
                'role': 'user',  # Firebase 用户默认角色
                'id_token': user_info['id_token'],
                'refresh_token': user_info['refresh_token'],
                'auth_provider': 'firebase'
            }
        else:
            return False, message, None
            
    except ImportError:
        return False, "Firebase Auth 模块未安装", None
    except Exception as e:
        logger.error(f"Firebase Auth 验证失败: {e}")
        return False, f"验证失败: {str(e)}", None


def _register_user_firebase(email: str, password: str, display_name: str, config: dict) -> tuple:
    """
    使用 Firebase Auth 注册新用户
    
    Returns:
        (success, message, user_info)
    """
    try:
        from utils.firebase_auth import get_firebase_auth, initialize_firebase_auth
        
        # 初始化 Firebase Auth
        auth_manager = get_firebase_auth()
        if not auth_manager.is_connected:
            if not initialize_firebase_auth(config):
                return False, "Firebase Auth 初始化失败", None
        
        # 注册
        success, message, user_info = auth_manager.register_with_email(email, password, display_name)
        
        if success:
            return True, message, {
                'username': user_info['display_name'],
                'uid': user_info['uid'],
                'email': user_info['email'],
                'role': 'user',
                'id_token': user_info['id_token'],
                'refresh_token': user_info['refresh_token'],
                'auth_provider': 'firebase'
            }
        else:
            return False, message, None
            
    except ImportError:
        return False, "Firebase Auth 模块未安装", None
    except Exception as e:
        logger.error(f"Firebase Auth 注册失败: {e}")
        return False, f"注册失败: {str(e)}", None


def show_login_page():
    """
    显示登录页面（旧版入口，包含 set_page_config）
    注意：此函数只应在独立调用时使用，不要在 main() 中调用
    """
    st.set_page_config(
        page_title="AI配音系统 - 登录",
        page_icon="🔐",
        layout="centered"
    )
    show_login_page_content()


def show_login_page_content():
    """
    显示登录页面内容（不含 set_page_config）
    
    支持两种认证模式：
    1. Firebase Auth（推荐）：支持注册、密码重置
    2. 本地配置：使用 config.yaml 中的用户配置
    """
    # 登录页面样式
    st.markdown("""
    <style>
    .login-container {
        max-width: 400px;
        margin: 100px auto;
        padding: 2rem;
        border-radius: 12px;
        border: 1px solid rgba(128, 128, 128, 0.2);
        background-color: rgba(128, 128, 128, 0.05);
    }
    .login-title {
        text-align: center;
        margin-bottom: 2rem;
    }
    .security-notice {
        font-size: 0.85rem;
        color: #888;
        text-align: center;
        margin-top: 1.5rem;
        padding: 0.75rem;
        border-radius: 8px;
        background: rgba(128, 128, 128, 0.1);
    }
    .auth-tabs {
        margin-bottom: 1.5rem;
    }
    .register-link {
        text-align: center;
        margin-top: 1rem;
        font-size: 0.9rem;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)
    
    # 获取配置
    try:
        from utils.config_manager import get_global_config_manager
        config_manager = get_global_config_manager()
        config = config_manager.load_config()
        security_config = config.get('security', {}) if config else {}
    except Exception as e:
        logger.error(f"读取安全配置失败: {e}")
        st.error("系统配置错误，请联系管理员")
        return
    
    # 检查认证模式
    use_firebase_auth = security_config.get('use_firebase_auth', False)
    
    if use_firebase_auth:
        _show_firebase_login_page(config, security_config)
    else:
        _show_local_login_page(security_config)


def _show_firebase_login_page(config: dict, security_config: dict):
    """显示 Firebase Auth 登录页面（支持注册和密码重置）"""
    
    # 初始化页面状态
    if 'auth_page_mode' not in st.session_state:
        st.session_state['auth_page_mode'] = 'login'
    
    page_mode = st.session_state['auth_page_mode']
    
    # 页面标题
    if page_mode == 'login':
        st.markdown("<div class='login-title'><h1>🔐 AI配音系统</h1><p>登录您的账号</p></div>", unsafe_allow_html=True)
    elif page_mode == 'register':
        st.markdown("<div class='login-title'><h1>📝 注册账号</h1><p>创建您的AI配音系统账号</p></div>", unsafe_allow_html=True)
    elif page_mode == 'reset':
        st.markdown("<div class='login-title'><h1>🔑 重置密码</h1><p>输入邮箱以接收重置链接</p></div>", unsafe_allow_html=True)
    
    # ===== 登录模式 =====
    if page_mode == 'login':
        email = st.text_input("📧 邮箱", key="firebase_email", placeholder="请输入邮箱地址")
        password = st.text_input("🔒 密码", type="password", key="firebase_password", placeholder="请输入密码")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("登录", use_container_width=True, type="primary", key="firebase_login_btn"):
                if not email:
                    st.error("请输入邮箱")
                    return
                if not password:
                    st.error("请输入密码")
                    return
                
                with st.spinner("正在登录..."):
                    success, message, user_info = _verify_user_firebase(email, password, config)
                
                if success:
                    # 设置登录状态
                    st.session_state['authenticated'] = True
                    st.session_state['auth_time'] = time.time()
                    st.session_state['auth_username'] = user_info.get('uid')  # 使用 UID 作为唯一标识
                    st.session_state['auth_display_name'] = user_info.get('username', email.split('@')[0])
                    st.session_state['auth_email'] = user_info.get('email')
                    st.session_state['auth_role'] = user_info.get('role', 'user')
                    st.session_state['auth_provider'] = 'firebase'
                    st.session_state['firebase_id_token'] = user_info.get('id_token')
                    st.session_state['firebase_refresh_token'] = user_info.get('refresh_token')
                    
                    logger.info(f"Firebase 用户登录成功 - Email: {email}, UID: {user_info.get('uid')}")
                    st.success(f"✅ 登录成功，欢迎 {st.session_state['auth_display_name']}！")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        
        # 注册和忘记密码链接
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📝 注册新账号", use_container_width=True, key="goto_register"):
                st.session_state['auth_page_mode'] = 'register'
                st.rerun()
        with col2:
            if st.button("🔑 忘记密码？", use_container_width=True, key="goto_reset"):
                st.session_state['auth_page_mode'] = 'reset'
                st.rerun()
    
    # ===== 注册模式 =====
    elif page_mode == 'register':
        display_name = st.text_input("👤 显示名称", key="reg_display_name", placeholder="您希望显示的名称")
        email = st.text_input("📧 邮箱", key="reg_email", placeholder="请输入邮箱地址")
        password = st.text_input("🔒 密码", type="password", key="reg_password", placeholder="至少 6 位字符")
        confirm_password = st.text_input("🔒 确认密码", type="password", key="reg_confirm", placeholder="再次输入密码")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("注册", use_container_width=True, type="primary", key="firebase_register_btn"):
                if not email:
                    st.error("请输入邮箱")
                    return
                if not password:
                    st.error("请输入密码")
                    return
                if len(password) < 6:
                    st.error("密码长度至少为 6 位")
                    return
                if password != confirm_password:
                    st.error("两次输入的密码不一致")
                    return
                
                with st.spinner("正在注册..."):
                    success, message, user_info = _register_user_firebase(
                        email, password, display_name or email.split('@')[0], config
                    )
                
                if success:
                    # 注册成功后自动登录
                    st.session_state['authenticated'] = True
                    st.session_state['auth_time'] = time.time()
                    st.session_state['auth_username'] = user_info.get('uid')
                    st.session_state['auth_display_name'] = user_info.get('username')
                    st.session_state['auth_email'] = user_info.get('email')
                    st.session_state['auth_role'] = 'user'
                    st.session_state['auth_provider'] = 'firebase'
                    st.session_state['firebase_id_token'] = user_info.get('id_token')
                    st.session_state['firebase_refresh_token'] = user_info.get('refresh_token')
                    
                    logger.info(f"Firebase 用户注册成功 - Email: {email}, UID: {user_info.get('uid')}")
                    st.success("✅ 注册成功！正在进入系统...")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"❌ {message}")
        
        # 返回登录
        st.markdown("---")
        if st.button("⬅️ 返回登录", use_container_width=True, key="back_to_login_from_reg"):
            st.session_state['auth_page_mode'] = 'login'
            st.rerun()
    
    # ===== 密码重置模式 =====
    elif page_mode == 'reset':
        email = st.text_input("📧 邮箱", key="reset_email", placeholder="请输入注册时使用的邮箱")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("发送重置链接", use_container_width=True, type="primary", key="firebase_reset_btn"):
                if not email:
                    st.error("请输入邮箱")
                    return
                
                with st.spinner("正在发送..."):
                    try:
                        from utils.firebase_auth import get_firebase_auth, initialize_firebase_auth
                        auth_manager = get_firebase_auth()
                        if not auth_manager.is_connected:
                            initialize_firebase_auth(config)
                        
                        success, message = auth_manager.send_password_reset_email(email)
                        
                        if success:
                            st.success(f"✅ {message}")
                            st.info("📬 请检查您的邮箱（包括垃圾邮件文件夹）")
                        else:
                            st.error(f"❌ {message}")
                    except Exception as e:
                        st.error(f"❌ 发送失败: {str(e)}")
        
        # 返回登录
        st.markdown("---")
        if st.button("⬅️ 返回登录", use_container_width=True, key="back_to_login_from_reset"):
            st.session_state['auth_page_mode'] = 'login'
            st.rerun()
    
    # 安全提示
    st.markdown("""
    <div class='security-notice'>
        🛡️ 您的数据安全由 Firebase Authentication 保护<br>
        密码经加密传输和存储
    </div>
    """, unsafe_allow_html=True)


def _show_local_login_page(security_config: dict):
    """显示本地配置认证登录页面"""
    
    st.markdown("<div class='login-title'><h1>🔐 AI配音系统</h1><p>请输入您的账号信息</p></div>", unsafe_allow_html=True)
    
    # 用户名输入框
    username = st.text_input("用户名", key="login_username", placeholder="请输入用户名")
    
    # 密码输入框
    password = st.text_input("密码", type="password", key="login_password", placeholder="请输入密码")
    
    # 检查账号是否被锁定
    is_locked, remaining_minutes = _check_account_locked(username, security_config) if username else (False, 0)
    
    if is_locked:
        st.error(f"🔒 账号已被临时锁定，请在 {remaining_minutes:.1f} 分钟后重试")
        st.markdown("<div class='security-notice'>⚠️ 多次登录失败会导致账号临时锁定</div>", unsafe_allow_html=True)
        return
    
    # 显示剩余尝试次数
    attempts_key = f'login_attempts_{username}'
    current_attempts = st.session_state.get(attempts_key, 0)
    max_attempts = security_config.get('max_login_attempts', 5)
    
    if current_attempts > 0:
        remaining_attempts = max_attempts - current_attempts
        if remaining_attempts <= 3:
            st.warning(f"⚠️ 剩余尝试次数: {remaining_attempts}")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("登录", use_container_width=True, type="primary"):
            if not username:
                st.error("请输入用户名")
                return
            
            if not password:
                st.error("请输入密码")
                return
            
            # 验证用户
            success, message, user_info = _verify_user(username, password, security_config)
            
            if success:
                # 记录登录成功
                _record_login_attempt(username, True, security_config)
                
                st.session_state['authenticated'] = True
                st.session_state['auth_time'] = time.time()
                st.session_state['auth_username'] = user_info.get('username', username)
                st.session_state['auth_display_name'] = user_info.get('username', username)
                st.session_state['auth_role'] = user_info.get('role', 'user')
                st.session_state['auth_provider'] = 'local'
                
                # 记录登录日志
                if security_config.get('log_access', True):
                    logger.info(f"用户登录成功 - 用户: {username}, 角色: {user_info.get('role', 'user')}, IP: {_get_client_ip()}")
                
                st.success(f"✅ {message}，欢迎 {st.session_state['auth_username']}！")
                time.sleep(0.5)  # 短暂显示成功消息
                st.rerun()
            else:
                # 记录登录失败
                _record_login_attempt(username, False, security_config)
                
                st.error(f"❌ {message}")
                
                # 记录失败日志
                if security_config.get('log_access', True):
                    logger.warning(f"登录失败 - 用户: {username}, 原因: {message}, IP: {_get_client_ip()}")
    
    # 安全提示
    st.markdown("""
    <div class='security-notice'>
        🛡️ 安全提示：请勿将账号密码透露给他人<br>
        连续登录失败将导致账号临时锁定
    </div>
    """, unsafe_allow_html=True)


def _get_client_ip() -> str:
    """获取客户端IP地址"""
    try:
        # 尝试从Streamlit获取客户端信息
        # 注意: 这需要Streamlit 1.18+版本
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            ctx = get_script_run_ctx()
            if ctx is not None:
                # 尝试获取session_id作为标识
                session_id = ctx.session_id[:8] if ctx.session_id else "unknown"
                return f"session:{session_id}"
        except:
            pass
        
        # 尝试从环境变量或请求头获取（Cloudflare等代理）
        import os
        cf_ip = os.environ.get('CF_CONNECTING_IP', '')
        if cf_ip:
            return cf_ip
        
        x_real_ip = os.environ.get('X_REAL_IP', '')
        if x_real_ip:
            return x_real_ip
        
        return "unknown"
    except Exception as e:
        logger.debug(f"获取客户端IP失败: {e}")
        return "unknown"


def _show_save_project_button():
    """显示保存工程按钮"""
    try:
        current_project = st.session_state.get('current_project')
        
        # 如果没有当前工程，不显示保存按钮
        if not current_project:
            return
        
        # 获取存储配置
        config = st.session_state.get('config', {})
        storage_config = config.get('storage', {})
        storage_backend = storage_config.get('backend', 'local')
        
        # 根据存储后端显示不同的图标和文字
        if storage_backend == 'firebase':
            save_icon = "☁️"
            save_text = "保存到云端"
            save_help = "将当前工程保存到 Firebase 云端存储"
        else:
            save_icon = "💾"
            save_text = "保存到本地"
            save_help = "将当前工程保存到本地存储"
        
        st.sidebar.markdown("### 💾 工程保存")
        
        # 显示当前存储模式
        storage_mode_text = "云端" if storage_backend == 'firebase' else "本地"
        st.sidebar.caption(f"存储模式: {storage_mode_text}")
        
        # 保存按钮
        if st.sidebar.button(f"{save_icon} {save_text}", key="save_project_btn", help=save_help, use_container_width=True):
            _execute_save_project(current_project, storage_backend)
        
    except Exception as e:
        logger.warning(f"显示保存按钮失败: {e}")


def _execute_save_project(project, storage_backend: str):
    """执行工程保存操作"""
    try:
        from models.project_dto import ProjectDTO
        
        if not isinstance(project, ProjectDTO):
            st.sidebar.error("❌ 无效的工程对象")
            return
        
        # 获取当前会话数据
        session_data = get_session_data()
        
        # 获取工程集成实例
        project_integration = get_user_project_integration()
        
        # 执行保存
        with st.sidebar:
            with st.spinner("正在保存..."):
                success = project_integration.save_project_state(project, session_data)
                
                # 如果是 Firebase 后端，确保刷新待保存的数据
                if storage_backend == 'firebase':
                    project_integration.flush_pending_saves()
        
        if success:
            storage_text = "云端" if storage_backend == 'firebase' else "本地"
            st.sidebar.success(f"✅ 工程已保存到{storage_text}")
            logger.info(f"手动保存工程成功: {project.name} -> {storage_backend}")
        else:
            st.sidebar.error("❌ 保存失败，请重试")
            logger.error(f"手动保存工程失败: {project.name}")
            
    except Exception as e:
        st.sidebar.error(f"❌ 保存出错: {str(e)}")
        logger.error(f"保存工程时发生错误: {e}")


def _show_progress_indicator():
    """显示当前工程进度指示器 - 极简版"""
    try:
        current_stage = st.session_state.get('processing_stage', 'project_home')
        current_project = st.session_state.get('current_project')
        
        # 定义工作流程核心步骤
        workflow_steps = [
            ('project_home', '工程管理'),
            ('segmentation', '智能分段'),
            ('language_selection', '配音设置'),
            ('translating', '翻译生成'),
            ('user_confirmation', '音频确认'),
            ('completion', '处理完成')
        ]
        
        # 显示当前工程名
        if current_project:
            project_name = getattr(current_project, 'name', '未知工程')
            st.sidebar.caption(f"当前工程: {project_name}")
        
        # 极简进度条
        stage_keys = [step[0] for step in workflow_steps]
        if current_stage in stage_keys:
            current_idx = stage_keys.index(current_stage)
            progress = (current_idx + 1) / len(workflow_steps)
            st.sidebar.progress(progress)
            st.sidebar.caption(f"进度: {workflow_steps[current_idx][1]} ({current_idx + 1}/{len(workflow_steps)})")
        
    except Exception as e:
        logger.warning(f"显示进度指示器失败: {e}")


def _is_stage_completed(stage_key: str, current_stage: str, workflow_steps: list) -> bool:
    """判断某个阶段是否已完成"""
    try:
        stage_keys = [step[0] for step in workflow_steps]
        current_index = stage_keys.index(current_stage) if current_stage in stage_keys else 0
        check_index = stage_keys.index(stage_key) if stage_key in stage_keys else -1
        
        return check_index < current_index
    except:
        return False


def clean_project_name(filename: str) -> str:
    """
    清理工程名称，移除特殊字符和不合适的格式
    
    Args:
        filename: 原始文件名
        
    Returns:
        清理后的工程名称
    """
    import re
    
    if not filename:
        return "新工程"
    
    # 移除常见的特殊字符和格式标记
    name = filename
    
    # 移除书名号
    name = re.sub(r'[《》]', '', name)
    
    # 移除括号内的内容（如 ALL(1), (1), [1] 等）
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    
    # 移除常见的版本标记
    name = re.sub(r'\bALL\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\bV\d+\b', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\b\d+\.\d+\b', '', name)  # 移除版本号如 1.0, 2.1
    
    # 移除多余的空格和特殊字符
    name = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', name)  # 保留中文、英文、数字和空格
    name = ' '.join(name.split())  # 合并多个空格
    
    # 限制长度
    name = name[:50] if len(name) > 50 else name
    
    # 如果清理后为空，使用默认名称
    if not name.strip():
        return "新工程"
    
    return name.strip()


def main():
    """主应用程序 - 纯状态机调度器"""
    
    # 🔥 网络配置（代理绕过等）- 在所有网络请求之前设置
    _setup_network_config()
    
    # 🔥 关键修复：st.set_page_config() 必须是第一个 Streamlit 命令
    # 在任何认证检查之前调用，避免注销后的配置冲突
    is_authenticated = st.session_state.get('authenticated', False)
    
    st.set_page_config(
        page_title="AI配音系统 - 登录" if not is_authenticated else "AI配音系统",
        page_icon="🔐" if not is_authenticated else "🎬",
        layout="centered" if not is_authenticated else "wide",
        initial_sidebar_state="collapsed" if not is_authenticated else "expanded"
    )
    
    # 安全认证检查
    if not check_authentication():
        show_login_page_content()  # 只渲染内容，不设置 page_config
        return
    
    # 注册程序退出时的清理函数（仅注册一次）
    if not st.session_state.get('_atexit_registered', False):
        import atexit
        from utils.project_integration import flush_all_pending_saves
        atexit.register(flush_all_pending_saves)
        st.session_state['_atexit_registered'] = True
        logger.debug("已注册程序退出时的数据保存处理")
    
    # Windows系统启动时清理临时文件
    from utils.windows_audio_utils import is_windows, cleanup_windows_temp_files
    if is_windows():
        try:
            cleaned_count = cleanup_windows_temp_files()
            if cleaned_count > 0:
                logger.info(f"Windows启动清理: 清理了 {cleaned_count} 个临时音频文件")
        except Exception as e:
            logger.warning(f"Windows启动清理失败: {e}")
    
    # 添加极简主题CSS
    st.markdown("""
    <style>
    /* 极简全局样式 */
    .stApp {
        background-color: transparent;
    }
    
    /* 标题样式 */
    .main-header {
        text-align: center;
        padding: 1.5rem 0;
        margin-bottom: 1rem;
    }
    .main-header h1 {
        font-weight: 300;
        letter-spacing: -0.5px;
    }
    
    /* 卡片容器 */
    .step-card {
        padding: 1.25rem;
        border-radius: 12px;
        border: 1px solid rgba(128, 128, 128, 0.2);
        margin: 1rem 0;
        background-color: rgba(128, 128, 128, 0.05);
        transition: all 0.3s ease;
    }
    
    /* 按钮美化 */
    .stButton > button {
        border-radius: 8px;
        font-weight: 400;
        transition: all 0.2s ease;
    }
    
    /* 侧边栏优化 */
    [data-testid="stSidebar"] {
        border-right: 1px solid rgba(128, 128, 128, 0.1);
    }
    
    /* 文本可见性修复 */
    .stMarkdown, .stText {
        color: inherit;
    }
    
    /* 状态指示器颜色 */
    .step-current {
        border-left: 3px solid #0066cc;
    }
    .step-completed {
        border-left: 3px solid #00cc66;
    }
    
    /* 隐藏不必要的元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)
    
    with st.sidebar:
        st.markdown("## AI配音系统")
        st.markdown("*智能SRT字幕翻译与配音*")
        
        # 安全注销按钮
        # 🔥 注意：注销逻辑不能在 try-except 中，因为 st.rerun() 会被捕获
        _config = None
        _security_enabled = False
        try:
            from utils.config_manager import get_global_config_manager
            config_manager = get_global_config_manager()
            _config = config_manager.load_config()
            _security_enabled = _config and _config.get('security', {}).get('enable_auth', False)
        except Exception as e:
            logger.debug(f"读取安全配置失败: {e}")
        
        if _security_enabled:
            # 显示当前登录用户
            display_name = get_current_display_name()
            auth_provider = st.session_state.get('auth_provider', 'local')
            auth_role = st.session_state.get('auth_role', 'user')
            
            # 角色和认证方式显示
            role_display = "管理员" if auth_role == "admin" else "用户"
            provider_icon = "🔥" if auth_provider == "firebase" else "🏠"
            
            st.caption(f"👤 {display_name} ({role_display}) {provider_icon}")
            
            # 显示邮箱（仅 Firebase 用户）
            auth_email = st.session_state.get('auth_email')
            if auth_email:
                st.caption(f"📧 {auth_email}")
            
            if st.button("🔓 注销", key="logout_btn", help="退出登录"):
                # 保存日志所需信息（在清理前）
                user_id = st.session_state.get('auth_username', 'unknown')
                current_auth_provider = st.session_state.get('auth_provider', 'local')
                
                # 清理所有认证相关的 session state（使用 del 彻底删除）
                auth_keys = [
                    'authenticated', 'auth_time', 'auth_username', 
                    'auth_display_name', 'auth_email', 'auth_role', 
                    'auth_provider', 'firebase_id_token', 'firebase_refresh_token',
                    'auth_page_mode'
                ]
                for key in auth_keys:
                    if key in st.session_state:
                        del st.session_state[key]
                
                # 明确设置为未认证状态
                st.session_state['authenticated'] = False
                st.session_state['auth_time'] = 0
                
                if _config and _config.get('security', {}).get('log_access', True):
                    logger.info(f"用户注销 - 用户: {user_id}, 认证方式: {current_auth_provider}, IP: {_get_client_ip()}")
                
                # 🔥 关键：st.rerun() 不能在 try-except 中
                st.rerun()
            st.divider()
        
        # TTS服务选择
        st.markdown("### 🎤 TTS设置")
        
        # 获取可用的TTS服务
        from tts import get_available_tts_services
        available_services = get_available_tts_services()
        
        # TTS服务下拉选择
        tts_service = st.selectbox(
            "TTS服务",
            options=list(available_services.keys()),
            index=0,  # 默认MiniMax
            format_func=lambda x: available_services[x],
            help="选择语音合成服务提供商",
            key="sidebar_tts_service"
        )
        
        # 语言选择器
        language_options = {
            "en": "🇺🇸 英语 (English)",
            "es": "🇪🇸 西班牙语 (Español)"
        }
        target_language = st.selectbox(
            "目标语言",
            options=list(language_options.keys()),
            index=0,  # 默认英语
            format_func=lambda x: language_options[x],
            help="选择配音的目标语言",
            key="sidebar_target_language"
        )
        
        # 根据选择的TTS服务和语言显示对应的音色选择
        voice_options = {}
        selected_voice_id = None
        
        if 'config' in st.session_state:
            tts_config = st.session_state['config'].get('tts', {})
            
            if tts_service == 'minimax':
                # MiniMax音色配置（多音色选择，与ElevenLabs保持一致）
                minimax_voices = tts_config.get('minimax', {}).get('voices', {})
                lang_voices = minimax_voices.get(target_language, {})
                
                if isinstance(lang_voices, dict) and lang_voices:
                    voice_options = lang_voices
                    
                    # 音色下拉选择
                    selected_voice_id = st.selectbox(
                        "选择音色",
                        options=list(voice_options.keys()),
                        format_func=lambda x: voice_options.get(x, x),
                        help="选择MiniMax语音音色",
                        key="sidebar_minimax_voice"
                    )
                    
                    # 显示选中音色的信息
                    if selected_voice_id:
                        st.success(f"✅ 已选择: {voice_options.get(selected_voice_id, selected_voice_id)}")
                else:
                    st.warning(f"⚠️ 未配置{target_language}语言的MiniMax音色")
                    
            elif tts_service == 'elevenlabs':
                # ElevenLabs音色配置（多音色选择）
                elevenlabs_voices = tts_config.get('elevenlabs', {}).get('voices', {})
                lang_voices = elevenlabs_voices.get(target_language, {})
                
                if isinstance(lang_voices, dict) and lang_voices:
                    voice_options = lang_voices
                    
                    # 音色下拉选择
                    selected_voice_id = st.selectbox(
                        "选择音色",
                        options=list(voice_options.keys()),
                        format_func=lambda x: voice_options.get(x, x),
                        help="选择ElevenLabs语音音色",
                        key="sidebar_elevenlabs_voice"
                    )
                    
                    # 显示选中音色的信息
                    if selected_voice_id:
                        st.success(f"✅ 已选择: {voice_options.get(selected_voice_id, selected_voice_id)}")
                else:
                    st.warning(f"⚠️ 未配置{target_language}语言的ElevenLabs音色")
                
                # 检查ElevenLabs API Key是否配置
                api_keys = st.session_state['config'].get('api_keys', {})
                elevenlabs_key = api_keys.get('elevenlabs_api_key', '')
                if not elevenlabs_key:
                    st.error("❌ ElevenLabs API Key未配置，请在config.yaml中设置")
        
        # 更新session_state中的配置
        if 'config' in st.session_state:
            st.session_state['config']['tts']['service'] = tts_service
            logger.debug(f"TTS服务已设置为: {tts_service}")
        
        # 保存语言选择和音色选择到session_state
        st.session_state['target_lang'] = target_language
        st.session_state['selected_tts_service'] = tts_service
        st.session_state['selected_voice_id'] = selected_voice_id
        
        # 显示当前设置状态
        with st.expander("🔧 当前设置详情", expanded=False):
            st.write(f"**TTS服务:** {available_services.get(tts_service, tts_service)}")
            st.write(f"**目标语言:** {language_options.get(target_language, target_language)}")
            if selected_voice_id:
                voice_display = voice_options.get(selected_voice_id, selected_voice_id) if voice_options else selected_voice_id
                st.write(f"**选中音色:** {voice_display}")
            else:
                st.write("**选中音色:** 未配置")
            
            # ElevenLabs特有设置显示
            if tts_service == 'elevenlabs' and 'config' in st.session_state:
                el_config = st.session_state['config'].get('tts', {}).get('elevenlabs', {})
                st.write(f"**模型:** {el_config.get('model_id', 'eleven_multilingual_v2')}")
                st.write(f"**稳定性:** {el_config.get('stability', 0.5)}")
                st.write(f"**相似度增强:** {el_config.get('similarity_boost', 0.75)}")
        
        st.markdown("---")
        
        # 保存工程按钮
        _show_save_project_button()
        
        st.markdown("---")
        
        # 显示当前工程进度
        _show_progress_indicator()
    
    # 加载配置 - 简化版本，避免循环
    config = load_configuration_simple()
    if not config:
        return
    
    # 🔥 关键修复：将配置保存到session_state中，供其他组件使用
    st.session_state['config'] = config
    
    # 检查处理阶段
    processing_stage = st.session_state.get('processing_stage', 'project_home')
    logger.debug(f"🔄 当前处理阶段: {processing_stage}")
    
    if processing_stage == 'project_home':
        # 工程管理主页 - 显示所有工程和创建新工程的界面
        logger.debug("🏠 进入工程管理主页")
        handle_project_management()
    elif processing_stage == 'file_upload':
        # 向后兼容的文件上传阶段
        logger.debug("📁 进入文件上传阶段（兼容模式）")
        handle_file_upload()
    else:
        # 其他所有阶段都委托给WorkflowManager
        logger.debug(f"🚀 处理阶段: {processing_stage}")
        workflow_manager = WorkflowManager(config)
        
        # 获取当前会话数据
        session_data = get_session_data()
        logger.debug(f"📊 会话数据状态: input_file_path={bool(session_data.get('input_file_path'))}, segments={len(session_data.get('segments', []))}, segmented_segments={len(session_data.get('segmented_segments', []))}")
        
        # 渲染当前阶段
        updated_session_data = workflow_manager.render_stage(processing_stage, session_data)
        
        # 更新会话数据
        update_session_data(updated_session_data)
        logger.debug(f"✅ 阶段处理完成，新状态: {updated_session_data.get('processing_stage', 'unknown')}")
        
        # 如果状态发生了变化，需要rerun来显示新的阶段
        if updated_session_data.get('processing_stage') != processing_stage:
            logger.info(f"状态转换: {processing_stage} → {updated_session_data.get('processing_stage')}")
            st.rerun()


def load_configuration_simple():
    """简化版配置加载 - 避免循环"""
    from utils.config_manager import get_global_config_manager
    config_manager = get_global_config_manager()
    
    try:
        config = config_manager.load_config()
        
        if config is not None:
            # 配置日志系统 - 在配置加载成功后立即设置
            setup_logging(config)
            
            # 验证配置文件
            is_valid, messages = config_manager.validate_config(config)
            
            if is_valid:
                st.sidebar.success("✅ 配置文件加载成功")
            else:
                st.sidebar.warning("⚠️ 配置文件存在问题")
                for message in messages:
                    if message.startswith("警告:"):
                        st.sidebar.warning(message)
                    else:
                        st.sidebar.error(message)
            
            return config
        else:
            # 如果没有配置文件，使用默认的INFO级别
            setup_logging(None, "INFO")
            st.sidebar.error("❌ 未找到配置文件")
            return None
            
    except Exception as e:
        # 如果加载失败，也要设置默认日志级别
        setup_logging(None, "INFO")
        st.sidebar.error(f"❌ 配置加载失败: {str(e)}")
        return None


def load_configuration():
    """加载配置 - 完整版本（暂时不使用）"""
    with st.sidebar:
        st.header("⚙️ 配置")
        
        from utils.config_manager import get_global_config_manager
        config_manager = get_global_config_manager()
        
        try:
            config = config_manager.load_config()
            
            if config is not None:
                # 验证配置文件
                is_valid, messages = config_manager.validate_config(config)
                
                if is_valid:
                    st.success("✅ 配置文件自动加载成功")
                else:
                    st.warning("⚠️ 配置文件加载成功但存在问题")
                
                # 显示配置信息
                config_info = config_manager.get_config_info()
                with st.expander("📋 配置详情"):
                    st.json({
                        "文件路径": config_info["path"],
                        "文件大小": config_info["size"],
                        "翻译模型": config_info["translation_model"],
                        "语音服务": "MiniMax TTS",
                        "支持语言": config_info["supported_languages"],
                        "语速设置": config_info["speech_rate"],
                        "音量设置": config_info["volume"],
                        "OpenAI密钥": "✅ 已配置" if config_info["has_openai_key"] else "❌ 未配置",
                    })
                
                # 显示验证消息
                if messages:
                    with st.expander("🔍 配置验证"):
                        for message in messages:
                            if message.startswith("警告:"):
                                st.warning(message)
                            else:
                                st.error(message)
                
                st.info(f"📂 配置文件: `{config_info['path']}`")
                
                # 重新加载按钮
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 重新加载", key="reload_config"):
                        if config_manager.reload_config():
                            st.success("重新加载成功")
                            # st.rerun()  # 注释掉，避免循环
                        else:
                            st.error("重新加载失败")
                
                with col2:
                    if st.button("⚙️ 手动配置", key="manual_config"):
                        config = None
                        # st.rerun()  # 注释掉，避免循环
                
                return config
                
            else:
                st.warning("⚠️ 未找到配置文件")
                
                # 显示搜索路径
                search_paths = config_manager.get_search_paths()
                with st.expander("📍 搜索路径"):
                    for i, path in enumerate(search_paths, 1):
                        path_obj = Path(path)
                        status = "✅ 存在" if path_obj.exists() else "❌ 不存在"
                        st.text(f"{i}. {path} - {status}")
                
                st.info("💡 请确保 config.yaml 文件存在于项目根目录")
                
                # 提供创建配置文件的选项
                if st.button("📝 创建默认配置文件", key="create_default_config"):
                    template = config_manager.get_config_template()
                    project_root = Path(__file__).parent.parent
                    config_path = project_root / "config.yaml"
                    
                    if config_manager.save_config(template, str(config_path)):
                        st.success(f"✅ 默认配置文件已创建: {config_path}")
                        st.info("请编辑配置文件并添加您的API密钥")
                        # st.rerun()  # 注释掉，避免循环
                    else:
                        st.error("❌ 创建配置文件失败")
                
                return None
                
        except Exception as e:
            st.error(f"❌ 配置管理器初始化失败: {str(e)}")
            return None


def handle_project_management():
    """处理工程管理主页"""
    try:
        project_view = ProjectManagementView()
        result = project_view.render_project_home()
        
        # 处理工程管理的返回结果
        action = result.get('action', 'none')
        
        if action == 'start_new_project':
            # 启动新工程流程
            project = result.get('project')
            if project and isinstance(project, ProjectDTO):
                st.session_state['current_project'] = project
                st.session_state['processing_stage'] = 'segmentation'
                logger.info(f"启动新工程: {project.name}")
                st.rerun()
        
        elif action == 'load_project':
            # 加载现有工程（传统方式）
            project_integration = get_user_project_integration()
            project_id = st.session_state.get('selected_project_id')
            
            if project_id:
                session_data = get_session_data()
                if project_integration.load_project_to_session(project_id, session_data):
                    update_session_data(session_data)
                    logger.info(f"加载工程成功: {project_id}")
                    st.rerun()
                else:
                    st.error("❌ 加载工程失败")
        
        elif action == 'load_project_stage':
            # 加载工程到指定阶段
            project_integration = get_user_project_integration()
            project_id = result.get('project_id') or st.session_state.get('selected_project_id')
            target_stage = result.get('target_stage')
            
            if project_id and target_stage:
                session_data = get_session_data()
                if project_integration.load_project_to_session(project_id, session_data):
                    # 处理 'translating' 这个过渡状态：根据实际数据判断应该进入哪个阶段
                    if target_stage == 'translating':
                        if session_data.get('translated_segments'):
                            # 已有翻译数据，进入音频确认
                            target_stage = 'user_confirmation'
                            logger.info("自动从 translating 跳转到 user_confirmation（已有翻译数据）")
                        elif session_data.get('confirmed_segments'):
                            # 有确认分段但没翻译，重新进入语言选择
                            target_stage = 'language_selection'
                            logger.info("自动从 translating 跳转到 language_selection（需要重新翻译）")
                        else:
                            # 没有必要数据，回到项目主页
                            target_stage = 'project_home'
                            logger.warning("translating 状态但缺少必要数据，回到项目主页")
                    
                    # 覆盖工程的processing_stage为用户选择的阶段
                    session_data['processing_stage'] = target_stage
                    update_session_data(session_data)
                    
                    # 清理阶段选择状态
                    if 'action' in st.session_state:
                        del st.session_state['action']
                    if 'selected_project_id' in st.session_state:
                        del st.session_state['selected_project_id']
                    
                    logger.info(f"加载工程成功并跳转到阶段: {project_id} -> {target_stage}")
                    st.rerun()
                else:
                    st.error("❌ 加载工程失败")
        
        elif action == 'create_new_project':
            # 跳转到文件上传页面创建新工程
            st.session_state['processing_stage'] = 'file_upload'
            logger.info("用户选择创建新工程，跳转到文件上传页面")
            st.rerun()
        
        elif action == 'back_to_home':
            # 返回工程管理主页
            st.rerun()
        
        elif action == 'project_imported':
            # 工程导入成功
            project = result.get('project')
            if project:
                st.success(f"✅ 工程导入成功: {project.name}")
                st.rerun()
        
        elif action == 'none':
            # 无操作，正常显示界面
            pass
        
        # 检查是否有工程管理页面的动作需要处理
        if 'action' in st.session_state:
            if st.session_state['action'] == 'load_project':
                project_id = st.session_state.get('selected_project_id')
                if project_id:
                    project_integration = get_user_project_integration()
                    session_data = get_session_data()
                    if project_integration.load_project_to_session(project_id, session_data):
                        update_session_data(session_data)
                        logger.info(f"加载工程成功: {project_id}")
                        # 清理动作状态
                        del st.session_state['action']
                        del st.session_state['selected_project_id']
                        st.rerun()
                    else:
                        st.error("❌ 加载工程失败")
                        del st.session_state['action']
                        if 'selected_project_id' in st.session_state:
                            del st.session_state['selected_project_id']
        
    except Exception as e:
        logger.error(f"工程管理页面处理失败: {e}")
        st.error(f"❌ 工程管理页面出现错误: {str(e)}")


def handle_file_upload():
    """处理文件上传阶段"""
    
    # 页面标题
    st.markdown('<div class="main-header"><h1>创建新的配音工程</h1><p>上传您的SRT字幕文件开始智能配音</p></div>', unsafe_allow_html=True)
    
    # 返回按钮
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("返回工程管理", key="back_to_project_home", use_container_width=True):
            st.session_state['processing_stage'] = 'project_home'
            st.rerun()
    
    st.markdown("### 第一步：上传SRT字幕文件")
    
    # 文件上传区域
    st.markdown('<div class="step-card">', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "上传SRT字幕文件",  # 非空 label（隐藏显示但用于可访问性）
        type=['srt'],
        help="支持标准SRT格式，包含中文字幕和时间码",
        label_visibility="collapsed"
    )
    if not uploaded_file:
        st.markdown("""
        <div style="text-align: center; padding: 2rem; color: #666;">
        <p style="font-size: 1.1rem; margin-bottom: 1rem;">请选择SRT字幕文件</p>
        <p style="font-size: 0.9rem;">支持UTF-8编码，最大10MB</p>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    if uploaded_file:
        # 清理上一个会话的临时文件
        if ('input_file_path' in st.session_state and 
            st.session_state.input_file_path and 
            os.path.exists(st.session_state.input_file_path)):
            try:
                os.unlink(st.session_state.input_file_path)
                logger.debug(f"清理了上一个临时文件: {st.session_state.input_file_path}")
            except Exception as e:
                logger.warning(f"清理旧的临时文件失败: {e}")

        # 验证文件大小
        if uploaded_file.size > 10 * 1024 * 1024:  # 10MB限制
            st.error("文件过大，请选择小于10MB的SRT文件")
            return
        
        # 保存上传的文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.srt') as tmp:
            tmp.write(uploaded_file.getvalue())
            input_file_path = tmp.name
        
        # 验证SRT文件格式
        if not validate_srt_file(input_file_path):
            st.error("❌ SRT文件格式不正确或文件损坏")
            st.markdown("**请确保文件符合以下要求:**")
            st.markdown("- 文件扩展名为 `.srt`")
            st.markdown("- 包含时间戳格式 (如: `00:00:01,000 --> 00:00:04,000`)")
            st.markdown("- 编码格式为 UTF-8 或 GBK")
            return
        
        # 显示文件信息
        file_info = get_file_info(input_file_path)
        if file_info:
            st.markdown('<div class="step-card step-completed">', unsafe_allow_html=True)
            st.markdown(f"**文件上传成功:** {file_info['name']}")
            
            # 文件信息展示
            col1, col2, col3 = st.columns(3)
            with col1:
                size_kb = file_info.get('size_kb', file_info.get('size', 0) / 1024)
                st.metric("文件大小", f"{size_kb:.2f} KB", label_visibility="visible")
            with col2:
                st.metric("文件类型", "SRT字幕", label_visibility="visible")
            with col3:
                st.metric("验证状态", "通过", label_visibility="visible")
            st.markdown('</div>', unsafe_allow_html=True)
            
            # 预览字幕内容
            show_subtitle_preview(input_file_path)
            
            # 工程创建设置
            st.markdown("### 第二步：配置工程信息")
            st.markdown('<div class="step-card step-current">', unsafe_allow_html=True)
            
            # 工程信息输入
            col1, col2 = st.columns(2)
            with col1:
                # 使用用户上传的原始文件名，而不是临时文件名
                original_filename = uploaded_file.name  # 获取用户上传的原始文件名
                project_name_key = f"project_name_input_{original_filename}"
                
                # 只在第一次设置默认值，使用原始文件名（不含扩展名）作为默认工程名
                if project_name_key not in st.session_state:
                    # 清理文件名，移除特殊字符和格式化
                    clean_name = clean_project_name(Path(original_filename).stem)
                    st.session_state[project_name_key] = clean_name
                
                project_name = st.text_input(
                    "工程名称",
                    help="为您的配音工程起个名字",
                    key=project_name_key
                )
            
            with col2:
                # 使用侧边栏的语言选择，如果没有则显示选择器
                sidebar_language = st.session_state.get('sidebar_target_language')
                if sidebar_language:
                    st.write("**目标语言**")
                    language_display = {"en": "🇺🇸 英语 (English)", "es": "🇪🇸 西班牙语 (Español)"}
                    st.info(f"已选择: {language_display.get(sidebar_language, sidebar_language)}")
                    st.caption("💡 可在左侧栏更改语言设置")
                    target_language = sidebar_language
                else:
                    target_language = st.selectbox(
                        "目标语言",
                        ["en", "es"],
                        format_func=lambda x: {"en": "🇺🇸 英语 (English)", "es": "🇪🇸 西班牙语 (Español)"}[x],
                        help="选择配音的目标语言",
                        key="file_upload_target_language"
                    )
            
            description = st.text_area(
                "工程描述（可选）", 
                placeholder="描述这个配音工程的用途、特点等...",
                help="可选的工程描述信息",
                key=f"project_description_input_{original_filename}"
            )
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # 创建工程按钮
            st.markdown('<div style="text-align: center; margin: 2rem 0;">', unsafe_allow_html=True)
            if st.button("创建工程并开始处理", type="primary", use_container_width=True, key="start_analysis"):
                # 获取用户输入的项目名称
                user_project_name = st.session_state.get(project_name_key, "").strip()
                
                # 验证输入
                if not user_project_name:
                    st.error("❌ 请输入工程名称")
                    return
                
                # 创建工程对象（如果还没有的话）
                if 'current_project' not in st.session_state:
                    try:
                        # 读取文件内容
                        with open(input_file_path, 'rb') as f:
                            file_content = f.read()
                        
                        # 创建工程
                        project_integration = get_user_project_integration()
                        filename = original_filename  # 使用原始文件名
                        
                        # 获取用户输入
                        user_description = st.session_state.get(f"project_description_input_{original_filename}", "").strip()
                        
                        project = project_integration.create_project_from_file(
                            filename, file_content, user_project_name, user_description
                        )
                        
                        if project:
                            # 设置目标语言
                            project.target_language = target_language
                            project.add_tags(["文件上传", "新创建"])
                            
                            # 保存工程
                            project_manager = get_user_project_integration().project_manager
                            if project_manager.save_project(project):
                                st.session_state['current_project'] = project
                                logger.info(f"创建工程成功: {project.name} (目标语言: {target_language})")
                                st.success(f"✅ 工程\"{user_project_name}\"创建成功！")
                            else:
                                st.error("❌ 工程保存失败")
                                return
                        else:
                            st.error("❌ 工程创建失败")
                            return
                    
                    except Exception as e:
                        st.error(f"❌ 创建工程时发生错误: {str(e)}")
                        logger.error(f"创建工程失败: {e}")
                        return
                
                # 保存文件路径到session state并进入下一阶段
                logger.info(f"🎯 开始分段分析，文件: {Path(input_file_path).name}")
                st.session_state.input_file_path = input_file_path
                st.session_state.processing_stage = 'segmentation'  # 直接进入分段阶段
                logger.debug(f"🔄 状态已设置为: {st.session_state.processing_stage}")
                st.rerun()  # 用户点击后需要刷新页面
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # 帮助信息
        with st.expander("SRT文件格式说明"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**标准格式示例:**")
                st.code("""1
00:00:01,000 --> 00:00:04,000
这是第一句中文字幕

2
00:00:05,000 --> 00:00:08,000
这是第二句中文字幕""", language="text")
            
            with col2:
                st.markdown("**文件要求:**")
                st.markdown("• 标准SRT格式")
                st.markdown("• UTF-8编码")
                st.markdown("• 包含时间戳")
                st.markdown("• 最大10MB")


def show_subtitle_preview(input_file_path: str):
    """显示字幕预览"""
    with st.expander("预览字幕内容"):
        try:
            from audio_processor.subtitle_processor import SubtitleProcessor
            subtitle_processor = SubtitleProcessor({})
            segments = subtitle_processor.load_subtitle(input_file_path)
            
            if segments:
                # 字幕统计信息
                total_duration = max(seg['end'] for seg in segments)
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("字幕片段数", len(segments))
                with col2:
                    st.metric("总时长", f"{total_duration:.1f}秒")
                with col3:
                    st.metric("平均时长", f"{total_duration/len(segments):.1f}秒/片段")
                
                # 显示前几个片段
                st.markdown("**字幕预览 (前5个片段):**")
                for i, seg in enumerate(segments[:5]):
                    st.markdown(f'<div style="background: #f8f9fa; padding: 0.5rem; margin: 0.5rem 0; border-radius: 4px; border-left: 3px solid #007bff;"><strong>片段 {i+1}</strong><br><small>{seg["start"]:.1f}s - {seg["end"]:.1f}s</small><br>{seg["text"]}</div>', unsafe_allow_html=True)
                
                if len(segments) > 5:
                    st.markdown(f'<div style="text-align: center; color: #666; margin: 1rem 0;">... 还有 {len(segments) - 5} 个片段</div>', unsafe_allow_html=True)
            else:
                st.warning("未能解析到字幕片段")
                
        except Exception as e:
            st.error(f"预览字幕失败: {str(e)}")
            st.markdown("**可能的原因:**")
            st.markdown("- 文件编码格式不支持")
            st.markdown("- SRT格式不规范")
            st.markdown("- 文件内容为空")


def get_session_data():
    """获取当前会话数据"""
    # 确保使用侧边栏的语言选择
    sidebar_language = st.session_state.get('sidebar_target_language')
    target_lang = sidebar_language or st.session_state.get('target_lang', 'en')  # 默认英语
    
    return {
        'processing_stage': st.session_state.get('processing_stage', 'file_upload'),
        'current_project': st.session_state.get('current_project'),  # 🔥 关键修复：添加当前工程
        'input_file_path': st.session_state.get('input_file_path'),
        'segments': st.session_state.get('segments', []),
        'segmented_segments': st.session_state.get('segmented_segments', []),
        'confirmed_segments': st.session_state.get('confirmed_segments', []),
        'translated_segments': st.session_state.get('translated_segments', []),
        'validated_segments': st.session_state.get('validated_segments', []),
        'optimized_segments': st.session_state.get('optimized_segments', []),
        'confirmation_segments': st.session_state.get('confirmation_segments', []),
        'translated_original_segments': st.session_state.get('translated_original_segments', []),
        'target_lang': target_lang,  # 使用侧边栏的语言选择
        'config': st.session_state.get('config'),
        'completion_results': st.session_state.get('completion_results'),
        'user_adjustment_choices': st.session_state.get('user_adjustment_choices', {}),
        'current_confirmation_index': st.session_state.get('current_confirmation_index', 0),
        'confirmation_page': st.session_state.get('confirmation_page', 1)
    }


def update_session_data(updated_data: Dict[str, Any]):
    """更新会话数据"""
    logger.debug(f"🔄 开始更新会话数据，收到 {len(updated_data)} 个更新项")
    
    for key, value in updated_data.items():
        st.session_state[key] = value
    
    # 记录状态转换
    old_stage = st.session_state.get('_previous_stage')
    new_stage = updated_data.get('processing_stage')
    if old_stage != new_stage:
        logger.debug(f"🎯 状态转换: {old_stage} → {new_stage}")
        st.session_state['_previous_stage'] = new_stage
    
    logger.debug(f"✅ 会话数据更新完成，当前状态: {new_stage}")


def reset_all_states():
    """重置所有状态"""
    # 清理临时文件
    if ('input_file_path' in st.session_state and 
        st.session_state.input_file_path and 
        os.path.exists(st.session_state.input_file_path)):
        try:
            os.unlink(st.session_state.input_file_path)
            logger.debug(f"清理了临时文件: {st.session_state.input_file_path}")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")

        keys_to_reset = [
        'processing_stage', 'segments', 'segmented_segments', 
        'confirmed_segments', 'target_lang', 'config', 'input_file_path',
        'completion_results', 'optimized_segments', 'confirmation_segments',
        'translated_original_segments', 'translated_segments', 'validated_segments',
        'current_confirmation_index', 'confirmation_page', 'user_adjustment_choices',
        # 分段视图的session_state
        'segmentation_edited_segments', 'segmentation_current_page', 'segmentation_original_segments'
    ]
    
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]
    
    # 重置为工程管理主页
    st.session_state['processing_stage'] = 'project_home'


def run_streamlit_app(config=None):
    """运行Streamlit应用"""
    if config:
        # 如果提供了配置，将其保存到会话状态
        st.session_state['config'] = config
    
    main()


if __name__ == "__main__":
    main() 