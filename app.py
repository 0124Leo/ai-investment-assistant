import streamlit as st
import pandas as pd
import os
import threading
import time
from openai import OpenAI
# ================= 配置区域 =================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-v4-flash"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'dataset_full.csv')

# 默认参数（可被 .streamlit/secrets.toml 覆盖）
DEFAULT_TOKEN = st.secrets.get("TOKEN", "")
DEFAULT_FAKEID = st.secrets.get("FAKEID", "")
DEFAULT_COOKIE = st.secrets.get("COOKIE", "")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
IS_LOCAL = st.secrets.get("LOCAL_MODE", "false") == "true"
# ===========================================

st.set_page_config(page_title="私募基金经理 AI 助手", page_icon="📈", layout="wide")

# ================= 密码保护 =================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 需要密码")
    if not APP_PASSWORD:
        st.error("未设置访问密码，请在 .streamlit/secrets.toml 中配置 APP_PASSWORD")
        st.stop()
    with st.form("login"):
        password = st.text_input("请输入访问密码", type="password")
        if st.form_submit_button("登录", type="primary"):
            if password == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("密码错误")
    st.stop()

# --- 状态管理初始化 ---
if 'running' not in st.session_state:
    st.session_state.running = False
if 'shared_data' not in st.session_state:
    st.session_state.shared_data = {'logs': [], 'progress': 0.0}
if 'stop_event' not in st.session_state:
    st.session_state.stop_event = threading.Event()
if 'worker_thread' not in st.session_state:
    st.session_state.worker_thread = None


# --- 数据加载 ---
@st.cache_data
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df = df.sort_values(by='Date', ascending=False)
            return df
        except Exception:
            return None
    return None


def get_relevant_context(df, query):
    if df is None or df.empty: return ""
    mask = df['Content'].astype(str).str.contains(query, case=False, na=False)
    filtered_df = df[mask]
    target_df = filtered_df.head(5) if not filtered_df.empty else df.head(5)
    context_text = ""
    for idx, row in target_df.iterrows():
        date = row['Date'].strftime('%Y-%m-%d') if pd.notnull(row['Date']) else "未知"
        content = str(row['Content'])[:600].replace('\n', ' ')
        context_text += f"--- 日期: {date} ---\n标题: {row['Title']}\n内容: {content}...\n\n"
    return context_text


# ================= 界面布局 =================
st.sidebar.title("🎛️ 系统菜单")
pages = ["💬 AI 知识库对话"]
if IS_LOCAL:
    pages.append("🔄 数据更新 (爬虫)")
page = st.sidebar.radio("选择功能", pages)

st.sidebar.divider()
df = load_data()
if df is not None:
    st.sidebar.success(f"📊 数据库状态: 正常\n文章数: {len(df)}")
else:
    st.sidebar.error("数据库未找到")

# ================= 页面 1: AI 对话 =================
if page == "💬 AI 知识库对话":
    st.title("📈 投资博主 AI 知识库")
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "你好！我是你的专属投资助理。"}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("输入问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        context = get_relevant_context(df, prompt)
        system_prompt = """你是一位全能型的金融投资助手。你拥有两个能力：
    1. **专属知识库**：你可以读取提供的【博主历史文章】。
    2. **通用知识**：你拥有深厚的金融学、经济学常识。
    请根据用户的问题类型，灵活选择回答策略：
    - **策略一（针对博主观点）**：如果用户问“博主最近怎么看”、“现在该加仓吗”、“提到什么板块”，**必须严格基于提供的文章内容回答**。如果文章没提，就实话实说“博主近期未提及”。
    - **策略二（针对通用知识）**：如果用户问“基金有哪些分类”、“什么是ETF”、“如何计算市盈率”等科普类问题，**请直接利用你的通用知识进行详细解答**，不需要管博主文章里有没有写。
    - **策略三（混合模式）**：如果用户问“博主提到的ETF是什么意思”，先解释ETF的定义（通用知识），再说明博主具体看好哪个ETF（专属知识）。"""
        user_input = f"""
    用户的问题是：{prompt}
    
    -----------------------------------
    【参考资料：博主近期文章片段】
    {context}
    -----------------------------------
    
    请根据上述规则开始回答：
    """

        with st.chat_message("assistant"):
            container = st.empty()
            full_res = ""
            try:
                client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)
                stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}],
                    stream=True, temperature=0.3
                )
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        full_res += chunk.choices[0].delta.content
                        container.write(full_res + "▌")
                container.write(full_res)
                st.session_state.messages.append({"role": "assistant", "content": full_res})
            except Exception as e:
                container.error(f"API 错误: {e}")

# ================= 页面 2: 数据更新 (多线程版，仅本地模式) =================
elif IS_LOCAL and page == "🔄 数据更新 (爬虫)":
    import crawler_backend
    st.title("🛠️ 数据采集控制台")

    # 按钮区域
    col1, col2 = st.columns([1, 1])
    with col1:
        start_btn = st.button("🚀 开始同步", disabled=st.session_state.running, type="primary")
    with col2:
        if st.session_state.running:
            if st.button("🛑 停止同步并保存"):
                st.session_state.stop_event.set()
                st.warning("已发送停止信号，正在保存数据...")

    # --- 开始逻辑 ---
    if start_btn and not st.session_state.running:
        if not all([DEFAULT_TOKEN, DEFAULT_COOKIE, DEFAULT_FAKEID]):
            st.error("配置缺失，请在 .streamlit/secrets.toml 中填写 Token、Cookie 和 FakeID")
        else:
            st.session_state.running = True
            st.session_state.stop_event.clear()
            st.session_state.shared_data = {'logs': ["准备开始..."], 'progress': 0.0}
            t = threading.Thread(
                target=crawler_backend.run_full_crawler_threaded,
                args=(DEFAULT_TOKEN, DEFAULT_COOKIE, DEFAULT_FAKEID, st.session_state.shared_data, st.session_state.stop_event)
            )
            t.start()
            st.session_state.worker_thread = t
            st.rerun()

    # --- 监控逻辑 ---
    if st.session_state.running:
        logs = st.session_state.shared_data['logs']
        prog = st.session_state.shared_data['progress']

        with st.status("正在采集数据...", expanded=True) as status:
            status.progress(prog)
            status.code("\n".join(logs[-15:]), language="text")

        if not st.session_state.worker_thread.is_alive():
            st.session_state.running = False
            st.success("✅ 任务结束（完成或已终止）")
            st.cache_data.clear()
            time.sleep(1)
            st.rerun()
        else:
            time.sleep(0.5)
            st.rerun()