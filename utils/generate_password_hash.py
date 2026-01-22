#!/usr/bin/env python3
"""
密码哈希生成工具
用于生成 config.yaml 中用户密码的 SHA256 哈希值
"""

import hashlib
import sys
import getpass


def generate_hash(password: str) -> str:
    """生成密码的 SHA256 哈希值"""
    return hashlib.sha256(password.encode()).hexdigest()


def main():
    print("=" * 50)
    print("🔐 密码哈希生成工具")
    print("=" * 50)
    print()
    
    if len(sys.argv) > 1:
        # 命令行参数模式
        password = sys.argv[1]
    else:
        # 交互模式（安全输入）
        password = getpass.getpass("请输入密码: ")
        confirm = getpass.getpass("请再次输入密码: ")
        
        if password != confirm:
            print("❌ 两次输入的密码不一致！")
            sys.exit(1)
    
    if not password:
        print("❌ 密码不能为空！")
        sys.exit(1)
    
    password_hash = generate_hash(password)
    
    print()
    print("✅ 生成的密码哈希值：")
    print("-" * 50)
    print(password_hash)
    print("-" * 50)
    print()
    print("📋 将此哈希值复制到 config.yaml 的 security.users 配置中：")
    print()
    print("users:")
    print("  your_username:")
    print(f'    password_hash: "{password_hash}"')
    print('    role: "user"  # 或 "admin"')
    print('    enabled: true')
    print()


if __name__ == "__main__":
    main()
