"""
本地数据更新脚本
用法: python3 update_data.py

从 .streamlit/secrets.toml 读取配置，运行爬虫更新 dataset_full.csv
可以配合 crontab 定时运行:
  0 9 * * 1 cd /path/to/ReptileProject && python3 update_data.py >> update.log 2>&1
"""
import os
import sys
import threading

# 读取 secrets.toml
try:
    import tomllib
except ImportError:
    import tomli as tomllib

secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
if not os.path.exists(secrets_path):
    print("❌ 未找到 .streamlit/secrets.toml")
    sys.exit(1)

with open(secrets_path, "rb") as f:
    secrets = tomllib.load(f)

token = secrets.get("TOKEN", "")
fakeid = secrets.get("FAKEID", "")
cookie = secrets.get("COOKIE", "")

if not all([token, cookie, fakeid]):
    print("❌ secrets.toml 中缺少 TOKEN / COOKIE / FAKEID")
    sys.exit(1)

# 导入爬虫模块
sys.path.insert(0, os.path.dirname(__file__))
import crawler_backend

# 运行爬虫
shared_data = {"logs": [], "progress": 0.0}
stop_event = threading.Event()

print("🚀 开始同步数据...")
success = crawler_backend.run_full_crawler_threaded(token, cookie, fakeid, shared_data, stop_event)

for log in shared_data["logs"]:
    print(log)

if success:
    print("✅ 数据更新完成")
else:
    print("⚠️ 数据更新未完全成功，请检查日志")
