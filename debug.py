import socket
import os
import psycopg2
import sys

print(f"Python Version: {sys.version}")
print(f"Psycopg2 Version: {psycopg2.__version__}")

# 1. 检查环境变量 (看看是不是有代理在捣乱)
print("\n--- [1] 环境变量检查 ---")
print(f"HTTP_PROXY: {os.environ.get('HTTP_PROXY', '未设置')}")
print(f"HTTPS_PROXY: {os.environ.get('HTTPS_PROXY', '未设置')}")

# 2. 纯 Socket 连接测试 (绕过 psycopg2 库，直接测试 Python 网络能力)
print("\n--- [2] 纯 Python Socket 测试 (127.0.0.1:5432) ---")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(('127.0.0.1', 5432))
    print("✅ Socket 连接成功！说明 Python 网络层是通的。")
    s.close()
except Exception as e:
    print(f"❌ Socket 连接失败: {e}")
    print("   -> 如果这里失败，说明 Python 被防火墙或代理软件彻底拦截了。")

# 3. Psycopg2 连接测试 (尝试关闭 SSL)
print("\n--- [3] Psycopg2 连接测试 (禁用 SSL) ---")
try:
    conn = psycopg2.connect(
        dbname="postgres",
        user="postgres",
        password="mysecretpassword", 
        host="127.0.0.1",
        port="5432",
        connect_timeout=3,
        sslmode='disable'  # <--- 关键：禁用 SSL，防止握手失败
    )
    print("✅ Psycopg2 连接成功！(SSL 已禁用)")
    conn.close()
except psycopg2.OperationalError as e:
    print("❌ 依然失败。具体的错误代码是：")
    print(f"---> {e}") 
except Exception as e:
    print(f"❌ 发生了其他错误: {e}")