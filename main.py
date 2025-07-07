import os
from dotenv import load_dotenv

# 1. 先載入 .env／Railway 上的環境變數
load_dotenv()

# 2. 無論任何情況都清除 proxy 相關環境變數
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)

# 3. 現在才 import OpenAI SDK
import openai

# 4. 其他套件
import traceback
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, List, Optional

# 5. LINE Bot SDK
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, StickerMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, StickerMessageContent, ImageMessageContent, VideoMessageContent
)


# 6. 建立 FastAPI 應用程式
app = FastAPI(title="LINE 智能聊天機器人", description="支援角色設定和預設 Prompt 的 LINE Bot")

# OpenAI 客戶端設定
openai.api_key = os.getenv("OPENAI_API_KEY")

# LINE Bot 設定
line_configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
line_handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# === 角色和預設 Prompt 設定 ===
CHATBOT_ROLES = {
    "客服代表": {
        "system_prompt": """你是一位專業且友善的客服代表。你的職責是：
        
**角色身份：**
- 代表公司與客戶互動
- 解決客戶問題和疑慮
- 提供優質的客戶服務體驗

**行為準則：**
- 始終保持禮貌、耐心和專業
- 主動聆聽客戶需求
- 提供清晰、準確的資訊
- 承認錯誤並積極尋求解決方案
- 請用與用戶相同語言回答

**溝通風格：**
- 使用溫暖、友善的語調
- 用繁體中文回答
- 避免過於技術性的術語
- 適時表達同理心

**限制範圍：**
- 不提供醫療、法律或財務建議
- 如問題超出專業範圍，請引導客戶聯繫相關專業人員""",
        "personality": "友善、耐心、專業"
    },
    "技術顧問": {
        "system_prompt": """你是一位資深技術顧問，專精於產品技術支援。

**專業領域：**
- 產品技術規格和功能說明
- 故障診斷和排除
- 最佳實務建議
- 系統整合指導

**回答方式：**
- 提供詳細且準確的技術資訊
- 使用循序漸進的解決步驟
- 包含具體的操作指引
- 必要時提供相關文件連結
- 請用與用戶相同語言回答

**溝通特色：**
- 專業但易懂的表達方式
- 適時使用技術術語並加以解釋
- 提供多種解決方案選項
- 確認客戶理解程度""",
        "personality": "專業、詳細、解決問題導向"
    }
}

# 預設設定
DEFAULT_ROLE = "客服代表"
DEFAULT_MODEL = "gpt-4o"
MAX_TOKENS = 1000
TEMPERATURE = 0.7

# 對話歷史儲存（以 LINE User ID 為 key）
conversation_history: Dict[str, List[Dict]] = {}

# === LINE Bot Webhook 處理 ===
@app.post("/callback")
async def line_callback(request: Request):
    """處理 LINE Webhook 請求"""
    signature = request.headers.get('X-Line-Signature', '')
    body = await request.body()
    
    try:
        line_handler.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return 'OK'

# Alias /webhook → /callback
@app.post("/webhook")
async def line_webhook(request: Request):
    return await line_callback(request)

@line_handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理 LINE 訊息事件"""
    user_id = event.source.user_id
    user_message = event.message.text
    
    # 檢查是否為角色切換指令
    if user_message.startswith("/角色"):
        handle_role_change(event, user_message)
        return
    
    # 檢查是否為重置指令
    if user_message == "/重置":
        handle_reset(event, user_id)
        return
    
    # 處理一般對話
    try:
        reply_text = generate_chatbot_response(user_id, user_message)
        
        with ApiClient(line_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    except Exception as e:
        # 錯誤處理
        error_message = "抱歉 😣 處理您的訊息時發生錯誤，請稍後再試。"
        with ApiClient(line_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=error_message)]
                )
            )

@line_handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker(event):
    # 可選擇回傳貼圖或文字
    with ApiClient(line_configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="收到你的貼圖了!")]
            )
        )

@line_handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(line_configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="收到你的圖片囉！請用文字簡單敘述影片的內容，能幫助我能更快速的理解您的問題喔!")]
            )
        )

@line_handler.add(MessageEvent, message=VideoMessageContent)
def handle_video(event):
    with ApiClient(line_configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="收到你的影片了！請用文字簡單敘述影片的內容，能幫助我能更快速的理解您的問題喔!")]
            )
        )

def handle_role_change(event, user_message):
    """處理角色切換"""
    user_id = event.source.user_id
    
    # 解析角色名稱
    try:
        role_name = user_message.split(" ")[1]
        if role_name in CHATBOT_ROLES:
            # 重新初始化該用戶的對話歷史
            role_config = CHATBOT_ROLES[role_name]
            conversation_history[user_id] = [
                {"role": "system", "content": role_config["system_prompt"]}
            ]
            reply_text = f"已切換為「{role_name}」角色！\n個性：{role_config['personality']}\n\n請開始對話吧！"
        else:
            available_roles = "、".join(CHATBOT_ROLES.keys())
            reply_text = f"找不到「{role_name}」角色。\n\n可用角色：{available_roles}\n\n使用方式：/角色 角色名稱"
    except IndexError:
        available_roles = "、".join(CHATBOT_ROLES.keys())
        reply_text = f"請指定角色名稱。\n\n可用角色：{available_roles}\n\n使用方式：/角色 角色名稱"
    
    with ApiClient(line_configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

def handle_reset(event, user_id):
    """處理重置對話"""
    if user_id in conversation_history:
        del conversation_history[user_id]
    
    reply_text = "對話已重置！請重新開始對話。\n\n💡 小提示：\n• 輸入 /角色 角色名稱 來切換角色\n• 輸入 /重置 來清除對話歷史"
    
    with ApiClient(line_configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

def generate_chatbot_response(user_id: str, message: str) -> str:
    """產生聊天機器人回應"""
    # 初始化或取得對話歷史
    if user_id not in conversation_history:
        role_config = CHATBOT_ROLES[DEFAULT_ROLE]
        conversation_history[user_id] = [
            {"role": "system", "content": role_config["system_prompt"]}
        ]
        # 發送歡迎訊息
        welcome_msg = (
            f"Hi 👋 你今天過得如何！\n\n"
            f"目前角色：{DEFAULT_ROLE}\n"
            f"個性：{role_config['personality']}\n\n"
            "💡 使用指令：\n"
            "• /角色 角色名稱 - 切換角色\n"
            "• /重置 - 清除對話歷史\n\n"
            "現在開始對話吧！"
        )
        return welcome_msg

    # 添加用戶訊息到歷史
    conversation_history[user_id].append({
        "role": "user",
        "content": message
    })

    # 呼叫 OpenAI API，並捕捉所有例外以便排錯
    try:
        response = openai.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=conversation_history[user_id],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE
        )
        bot_reply = response.choices[0].message.content
    except Exception as e:
        # 把完整錯誤堆疊印到 stdout（Railway 的 Logs → Observability 裡可見）
        traceback.print_exc()
        # 將錯誤內容短訊回傳給使用者（測試用，可改回原本錯誤訊息）
        return f"⚠️ Internal Error: {str(e)}"

    # 將回應添加到歷史
    conversation_history[user_id].append({
        "role": "assistant",
        "content": bot_reply
    })

    return bot_reply

# === API 端點（供測試使用）===
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    role: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    role: str
    session_id: str

@app.get("/")
async def welcome():
    """API 歡迎頁面"""
    return {
        "message": "LINE 智能聊天機器人 API",
        "version": "2.0.0",
        "line_bot": "active",
        "available_roles": list(CHATBOT_ROLES.keys()),
        "endpoints": {
            "line_callback": "/callback - LINE Webhook 端點",
            "chat": "/chat - 一般聊天 API（測試用）"
        }
    }

@app.get("/health")
async def health():
    """健康檢查端點"""
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
async def chat_with_bot(request: ChatRequest):
    """一般聊天 API（供測試使用）"""
    try:
        current_role = request.role if request.role and request.role in CHATBOT_ROLES else DEFAULT_ROLE
        reply = generate_chatbot_response(request.session_id, request.message)
        
        return ChatResponse(
            reply=reply,
            role=current_role,
            session_id=request.session_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"處理訊息時發生錯誤: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    print("🤖 LINE 智能聊天機器人啟動中...")
    print(f"📋 可用角色: {list(CHATBOT_ROLES.keys())}")
    print(f"🎭 預設角色: {DEFAULT_ROLE}")
    print("=" * 50)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
