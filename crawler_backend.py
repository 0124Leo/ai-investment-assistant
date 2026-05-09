import requests
import time
import random
import csv
import re
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta


# 这是一个后端工具文件，负责执行具体的爬虫逻辑

def run_full_crawler_threaded(token, cookie, fakeid, shared_data, stop_event):
    """
    shared_data: 一个字典，用于和前端共享状态 {'log': [], 'progress': 0.0}
    stop_event: 线程事件，用于接收停止信号
    """

    # 辅助函数：写日志
    def add_log(msg):
        # 将日志追加到列表中
        shared_data['logs'].append(msg)
        # 保持只显示最近 10 条
        if len(shared_data['logs']) > 10:
            shared_data['logs'] = shared_data['logs'][-10:]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Referer": f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&appmsgid=100000076&token={token}&lang=zh_CN"
    }

    # ================= 阶段一：获取文章列表 =================
    add_log("🚀 阶段一启动：正在获取文章列表...")

    url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
    data_list = []

    # 默认爬取半年
    deadline = datetime.now() - timedelta(days=180)
    deadline_ts = int(deadline.timestamp())

    page = 0
    is_finished = False

    # 限制最多爬 20 页
    while page < 20 and not is_finished:
        # 🛑 检查停止信号
        if stop_event.is_set():
            add_log("🛑 检测到停止信号，正在结束阶段一...")
            break

        begin = page * 5
        params = {
            "action": "list_ex", "begin": str(begin), "count": "5",
            "fakeid": fakeid, "type": "9", "query": "",
            "token": token, "lang": "zh_CN", "f": "json", "ajax": "1"
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            res_json = resp.json()

            # 检查返回码
            ret = res_json.get('base_resp', {}).get('ret')
            if ret != 0:
                add_log(f"❌ 微信接口报错 (ret={ret})。")
                return False

            msg_list = res_json.get('app_msg_list', [])
            if not msg_list:
                add_log("✅ 已无更多文章。")
                break

            for item in msg_list:
                create_time = item.get('create_time')
                title = item.get('title')
                link = item.get('link')
                date_str = time.strftime('%Y-%m-%d', time.localtime(create_time))

                if create_time < deadline_ts:
                    add_log(f"⏹ 发现半年前文章 [{date_str}]，停止列表抓取。")
                    is_finished = True
                    break

                data_list.append({'Title': title, 'Link': link, 'Date': date_str})
                add_log(f"   - 捕获: [{date_str}] {title}")

            if is_finished:
                break

            page += 1

            # 更新进度 (前50%)
            raw_prog = 0.05 + (page * 0.02)
            shared_data['progress'] = min(raw_prog, 0.5)

            # 休息时也要检查停止信号
            for _ in range(3):
                if stop_event.is_set(): break
                time.sleep(1)

        except Exception as e:
            add_log(f"❌ 网络请求错误: {e}")
            return False

    if not data_list:
        add_log("⚠️ 未获取到任何文章链接 (或被提前终止)。")
        return False

    add_log(f"✅ 阶段一结束，共获取 {len(data_list)} 篇链接。")

    # ================= 阶段二：下载正文 =================
    # 只有当没有被强制停止，或者虽然停止了但有一点数据时，继续尝试保存

    if stop_event.is_set():
        add_log("⚠️ 已触发停止，跳过阶段二下载，直接保存已有列表...")
    else:
        add_log("🚀 阶段二启动：正在下载正文...")

    final_data = []
    total = len(data_list)

    # 如果阶段一就被停了，这里的 data_list 可能只有一部分，但我们依然处理它
    for i, item in enumerate(data_list):
        # 🛑 检查停止信号
        if stop_event.is_set():
            add_log("🛑 检测到停止信号，正在中止下载...")
            break

        # 更新进度 (0.5 - 1.0)
        current_progress = 0.5 + ((i + 1) / total) * 0.5
        shared_data['progress'] = min(current_progress, 1.0)

        link = item['Link']
        try:
            r = requests.get(link, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                content_div = soup.find('div', id='js_content')

                if content_div:
                    text = content_div.get_text(separator='\n').strip()
                    pattern = r'(?<!\d)((?:00|01|11|12|15|16|30|51|56|58|60|68)\d{4})(?!\d)'
                    codes = list(set(re.findall(pattern, text)))

                    final_data.append({
                        'Date': item['Date'],
                        'Title': item['Title'],
                        'Link': link,
                        'Codes': ', '.join(codes),
                        'Content': text
                    })
                    add_log(f"   ok: {item['Title']}")
                else:
                    add_log(f"   skip: {item['Title']} (无正文)")
        except:
            add_log(f"   error: {item['Title']} 下载失败")

        time.sleep(random.randint(1, 2))

    # ================= 保存结果 =================
    # 无论是否被 Stop，只要有数据就保存
    if final_data:
        df = pd.DataFrame(final_data)
        df.to_csv('dataset_full.csv', index=False, encoding='utf-8-sig')
        add_log("🎉 数据已保存！(dataset_full.csv)")
        shared_data['progress'] = 1.0  # 强制设为完成
        return True
    elif data_list and stop_event.is_set():
        # 如果只有列表没有正文（在阶段二刚开始就停了）
        df = pd.DataFrame(data_list)
        df.to_csv('articles_list.csv', index=False, encoding='utf-8-sig')
        add_log("⚠️ 只有链接列表被保存 (articles_list.csv)")
        return True
    else:
        add_log("❌ 数据为空，未保存。")
        return False