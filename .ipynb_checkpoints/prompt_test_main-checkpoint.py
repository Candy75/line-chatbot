import os
import weaviate
import time
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from openai import OpenAI
from weaviate import Client
from weaviate import AuthApiKey, ConnectionParams, WeaviateClient

# ─── 環境變數 ─────────────────────────
API_KEY = os.getenv("OPENAI_APIKEY")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "localhost")
HTTP_PORT = int(os.getenv("WEAVIATE_HTTP_PORT", 8080))
GRPC_PORT = int(os.getenv("WEAVIATE_GRPC_PORT", 50051))

# ─── FastAPI + OpenAI 客戶端 ───────────
app = FastAPI()
openai_client = OpenAI(api_key=API_KEY)
wv_client: Optional[WeaviateClient] = None

def get_wv_client() -> weaviate.WeaviateClient:
    return weaviate.connect_to_custom(
        http_host="weaviate",
        http_port=8080,
        http_secure=False,
        grpc_host="weaviate",
        grpc_port=50051,
        grpc_secure=False,
        headers={"X-OpenAI-Api-Key": API_KEY},
    )

# ─── （可選）健康檢查路由 ─────────────────
@app.get("/health")
def health():
    return {"status": "ok"}

# ─── 查詢模型 ────────────────────────────
class Query(BaseModel):
    message: str
    role: Optional[str] = None
    system_prompt: Optional[str] = None

class RoleConfig(BaseModel):
    role_name: str
    system_prompt: str
    description: Optional[str] = None

class ChatSession(BaseModel):
    session_id: str
    role_config: Optional[RoleConfig] = None
    chat_history: List[dict] = []

# ─── 內建角色配置 ────────────────────────
DEFAULT_ROLES = {
    "助理": RoleConfig(
        role_name="助理",
        system_prompt="你是一個專業的助理，會根據提供的產品資訊來回答用戶的問題。請用繁體中文回答，語氣要友善且專業。",
        description="通用助理角色"
    ),
    "銷售專員": RoleConfig(
        role_name="銷售專員",
        system_prompt="你是一位專業的銷售專員，擅長推薦產品並解答客戶疑問。請根據產品資訊提供詳細的產品說明，並主動推薦相關產品。用熱情友善的語氣回答。",
        description="專業銷售人員角色"
    ),
    "技術顧問": RoleConfig(
        role_name="技術顧問",
        system_prompt="你是一位技術顧問，專門提供產品的技術細節和規格說明。請用專業但易懂的方式解釋技術問題，並提供實用的建議。",
        description="技術專家角色"
    ),
    "客服代表": RoleConfig(
        role_name="客服代表",
        system_prompt="你是一位耐心的客服代表，專門處理客戶的問題和投訴。請用同理心回應客戶，提供解決方案，並確保客戶滿意。",
        description="客戶服務專員角色"
    )
}

# ─── 會話管理 ────────────────────────────
chat_sessions = {}

def retrieve_context(query: str, top_k: int = 3) -> list[str]:
    client = get_wv_client()
    # 1) 取得 Product 這個 collection
    product_col = client.collections.get("Product")
    # 2) 呼叫 collection.query.near_text
    response = product_col.query.near_text(
        query=query,
        limit=top_k,
    )
    # 3) 回傳 description 欄位
    return [
        obj.properties.get("description", "")
        for obj in response.objects
    ]

@app.get("/roles")
def get_available_roles():
    """取得所有可用的角色配置"""
    return {"roles": DEFAULT_ROLES}

@app.post("/set_role")
def set_role(session_id: str, role_name: str):
    """設定會話的角色"""
    if role_name not in DEFAULT_ROLES:
        return {"error": f"角色 '{role_name}' 不存在"}
    
    if session_id not in chat_sessions:
        chat_sessions[session_id] = ChatSession(
            session_id=session_id,
            role_config=DEFAULT_ROLES[role_name],
            chat_history=[]
        )
    else:
        chat_sessions[session_id].role_config = DEFAULT_ROLES[role_name]
        # 清空聊天歷史，因為角色已改變
        chat_sessions[session_id].chat_history = []
    
    return {
        "message": f"已設定角色為：{role_name}",
        "role_config": DEFAULT_ROLES[role_name]
    }

@app.post("/custom_role")
def set_custom_role(session_id: str, role_config: RoleConfig):
    """設定自定義角色"""
    if session_id not in chat_sessions:
        chat_sessions[session_id] = ChatSession(
            session_id=session_id,
            role_config=role_config,
            chat_history=[]
        )
    else:
        chat_sessions[session_id].role_config = role_config
        # 清空聊天歷史，因為角色已改變
        chat_sessions[session_id].chat_history = []
    
    return {
        "message": f"已設定自定義角色：{role_config.role_name}",
        "role_config": role_config
    }

@app.post("/chat")
def chat(q: Query, session_id: str = "default"):
    try:
        # 初始化會話（如果不存在）
        if session_id not in chat_sessions:
            chat_sessions[session_id] = ChatSession(
                session_id=session_id,
                role_config=DEFAULT_ROLES["助理"],  # 預設角色
                chat_history=[]
            )
        
        session = chat_sessions[session_id]
        
        # 取得產品相關資訊
        snippets = retrieve_context(q.message)
        
        # 建構系統提示詞
        system_prompt = ""
        
        # 使用會話中的角色配置
        if session.role_config:
            system_prompt = session.role_config.system_prompt
        # 或使用請求中的自定義提示詞
        elif q.system_prompt:
            system_prompt = q.system_prompt
        # 或使用請求中的角色
        elif q.role and q.role in DEFAULT_ROLES:
            system_prompt = DEFAULT_ROLES[q.role].system_prompt
        else:
            system_prompt = DEFAULT_ROLES["助理"].system_prompt
        
        # 加入產品資訊到系統提示詞
        if snippets:
            system_prompt += f"\n\n以下是相關的產品資訊：\n" + "\n---\n".join(snippets)
        
        # 建構訊息列表
        messages = [{"role": "system", "content": system_prompt}]
        
        # 加入聊天歷史
        messages.extend(session.chat_history)
        
        # 加入當前用戶訊息
        messages.append({"role": "user", "content": q.message})
        
        # 呼叫 OpenAI API
        result = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        
        assistant_reply = result.choices[0].message.content
        
        # 更新聊天歷史
        session.chat_history.append({"role": "user", "content": q.message})
        session.chat_history.append({"role": "assistant", "content": assistant_reply})
        
        # 限制歷史長度（保留最近10輪對話）
        if len(session.chat_history) > 20:
            session.chat_history = session.chat_history[-20:]
        
        return {
            "reply": assistant_reply,
            "session_id": session_id,
            "current_role": session.role_config.role_name if session.role_config else "未設定",
            "chat_history_length": len(session.chat_history) // 2
        }
        
    except Exception as e:
        # 印出 traceback 到 console
        import traceback; traceback.print_exc()
        # 前端收到錯誤也好判斷
        return {"error": str(e)}

@app.get("/chat_history/{session_id}")
def get_chat_history(session_id: str):
    """取得指定會話的聊天歷史"""
    if session_id not in chat_sessions:
        return {"error": "會話不存在"}
    
    session = chat_sessions[session_id]
    return {
        "session_id": session_id,
        "role_config": session.role_config,
        "chat_history": session.chat_history
    }

@app.delete("/chat_history/{session_id}")
def clear_chat_history(session_id: str):
    """清空指定會話的聊天歷史"""
    if session_id not in chat_sessions:
        return {"error": "會話不存在"}
    
    chat_sessions[session_id].chat_history = []
    return {"message": f"已清空會話 {session_id} 的聊天歷史"}

# ─── 靜態頁面設定 ─────────────────────────
@app.get("/")
def get_index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
