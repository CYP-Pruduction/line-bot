# line_app.py
# 副本管理 LINE Bot 應用程式
# 使用 Flask 和 LINE Messaging API 開發的活動管理機器人
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
from linebot.v3.messaging import (
    TextMessage,
    ReplyMessageRequest,
    FlexMessage,
    FlexContainer
)
import logging
from datetime import datetime
import os
import asyncio

# 初始化 Flask 應用程式
app = Flask(__name__)

# 環境變數配置
# 處理資料庫連線 URL，確保使用 PostgreSQL 協議
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://')

# 配置資料庫連線
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 配置日誌系統
# 設定日誌級別和輸出格式，便於追蹤和除錯
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 從環境變數獲取 LINE Bot 驗證憑證
# 這些憑證用於與 LINE Messaging API 進行安全通訊
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')

# 配置 LINE Bot 客戶端
configuration = Configuration(access_token=channel_access_token)
api_client = ApiClient(configuration)
messaging_api = MessagingApi(api_client)
handler = WebhookHandler(channel_secret)

# 資料庫模型定義
# 定義 Activity（副本）模型，用於儲存活動/副本資訊
class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # 唯一識別碼
    name = db.Column(db.String(100), nullable=False) # 副本名稱
    datetime = db.Column(db.String(30), nullable=False) # 副本日期時間
    creator_id = db.Column(db.String(50), nullable=False)  # 創建者的 LINE User ID
    participants = db.relationship('Participant', backref='activity', lazy=True) # 參與者關聯

# 定義 Participant（參與者）模型，用於儲存參與活動的用戶資訊
class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True) # 唯一識別碼
    user_id = db.Column(db.String(50), nullable=False) # LINE User ID
    user_name = db.Column(db.String(100)) # 用戶顯示名稱
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False) # 關聯的副本 ID


# 使用者狀態追蹤字典
# 用於追蹤用戶在副本建立過程中的當前步驟
user_states = {}

# 非同步函數：獲取 LINE 用戶資料
async def get_user_profile(user_id):
    """
    從 LINE 獲取用戶個人資料

    :param user_id: LINE 用戶唯一識別碼
    :return: 用戶顯示名稱，若發生錯誤則返回 "未知用戶"
    """
    try:
        profile = await messaging_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return "未知用戶"

# 輔助函數：執行非同步協程
def run_async(coro):
    """
    協助執行非同步函數的輔助函數

    :param coro: 要執行的非同步協程
    :return: 協程執行結果
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# 建立副本名稱輸入的 Flex 訊息
def create_activity_name_input():
    """
    創建一個引導用戶輸入副本名稱的 Flex 訊息

    :return: FlexMessage 物件
    """
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "建立新副本",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#1DB446"
                },
                {
                    "type": "separator",
                    "margin": "lg"
                },
                {
                    "type": "text",
                    "text": "請輸入副本名稱",
                    "margin": "lg"
                }
            ]
        }
    }
    return FlexMessage(
        alt_text="輸入副本名稱",
        contents=FlexContainer.from_dict(flex_content)
    )

# 建立日期時間選擇器的 Flex 訊息
def create_datetime_picker_flex():
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "選擇副本時間",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#1DB446"
                },
                {
                    "type": "separator",
                    "margin": "lg"
                },
                {
                    "type": "button",
                    "style": "primary",
                    "margin": "md",
                    "action": {
                        "type": "datetimepicker",
                        "label": "選擇日期時間",
                        "data": "action=select_date",
                        "mode": "datetime"
                    }
                }
            ]
        }
    }
    return FlexMessage(
        alt_text="選擇副本時間",
        contents=FlexContainer.from_dict(flex_content)
    )

# 建立副本列表的 Flex 訊息
def create_activities_list_flex():
    """
    創建顯示所有副本的 Flex 訊息列表

    :return: FlexMessage 或 TextMessage 物件
    """
    # 查詢所有副本
    activities = Activity.query.all()

    # 如果沒有副本，返回提示訊息
    if not activities:
        return TextMessage(text="目前沒有任何副本")

    # 建立副本列表的 Flex 訊息內容
    contents = []
    for activity in activities:
        # 副本資訊
        activity_info = [
            {
                "type": "text",
                "text": activity.name,
                "weight": "bold",
                "size": "lg"
            },
            {
                "type": "text",
                "text": f"日期: {activity.datetime.split()[0]}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"時間: {activity.datetime.split()[1]}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"參加人數: {len(activity.participants)}",
                "size": "sm"
            }
        ]

        # 按鈕列
        buttons = {
            "type": "box",
            "layout": "horizontal",
            "margin": "sm",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "flex": 2,  # 調整為更大的 flex 值
                    "adjustMode": "shrink-to-fit",  # 添加自動調整模式
                    "action": {
                        "type": "postback",
                        "label": "報名",
                        "data": f"action=join_activity&id={activity.id}"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "flex": 2,
                    "adjustMode": "shrink-to-fit",
                    "action": {
                        "type": "postback",
                        "label": "取消",
                        "data": f"action=cancel_join&id={activity.id}"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "flex": 2,
                    "adjustMode": "shrink-to-fit",
                    "action": {
                        "type": "postback",
                        "label": "名單",
                        "data": f"action=view_participants&id={activity.id}"
                    }
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "flex": 2,
                    "adjustMode": "shrink-to-fit",
                    "color": "#dc3545",
                    "action": {
                        "type": "postback",
                        "label": "移除",
                        "data": f"action=delete_activity&id={activity.id}"
                    }
                }
            ]
        }

        # 將副本信息和按鈕組合在一起
        contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": activity_info + [buttons]
        })

    # 構建完整的 Flex 訊息
    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "副本列表",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#1DB446"
                },
                {
                    "type": "separator",
                    "margin": "lg"
                }
            ] + contents
        }
    }
    return FlexMessage(
        alt_text="副本列表",
        contents=FlexContainer.from_dict(flex_content)
    )

# LINE Webhook 回調路由
@app.route("/callback", methods=['POST'])
def callback():
    """
    處理來自 LINE 的 Webhook 回調
    驗證簽名並觸發事件處理
    """
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        logger.error(f"Error: {e}")
    return 'OK'

# 文字訊息事件處理器
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """
    處理使用者發送的文字訊息
    支援多種指令，包括創建副本、查看副本、刪除副本等

    :param event: LINE 訊息事件
    """
    try:
        user_id = event.source.user_id
        text = event.message.text

        # 處理各種文字指令
        # 刪除所有副本確認流程
        if text == "刪除所有副本":
            # 創建確認刪除的 Flex 訊息
            confirmation_message = FlexMessage(
                alt_text="確認刪除所有副本？",
                contents=FlexContainer.from_dict({
                   "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                         "contents": [
                            {
                                "type": "text",
                                "text": "確認刪除所有副本？",
                                "weight": "bold",
                                "size": "xl",
                                "align": "center"
                            },
                             {
                                "type": "separator",
                                "margin": "lg"
                            },
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "margin": "md",
                                "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "button",
                                        "style": "primary",
                                        "height": "sm",
                                         "action": {
                                            "type": "postback",
                                            "label": "是",
                                            "data": "action=confirm_delete_all"
                                            }
                                    },
                                    {
                                         "type": "button",
                                         "style": "secondary",
                                         "height": "sm",
                                         "action": {
                                              "type": "postback",
                                              "label": "否",
                                              "data": "action=cancel_delete_all"
                                          }
                                    }
                                ]
                             }
                         ]
                     }
                })
            )
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[confirmation_message]
            )
            messaging_api.reply_message(request)
            return

        # 建立新副本流程
        if text.startswith("副本 "):
            # 引導用戶選擇副本日期時間
            activity_name = text[3:].strip()
            if activity_name:
                user_states[user_id] = {
                    'step': 'datetime',
                    'name': activity_name
                }
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[create_datetime_picker_flex()]
                )
                messaging_api.reply_message(request)
            else:
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請輸入副本名稱，例如：副本 副本")]
                )
                messaging_api.reply_message(request)
        # 列出所有副本
        elif text == "副本":
            # 顯示所有現有副本的列表
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[create_activities_list_flex()]
            )
            messaging_api.reply_message(request)

    except Exception as e:
        logger.error(f"Error: {e}")


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    try:
        user_id = event.source.user_id
        text = event.message.text

        # 新增人員指令處理
        if text.startswith("+ "):
            parts = text.split(" ")
            if len(parts) == 3:
                activity_name = parts[1]
                new_participant_name = parts[2]

                # 尋找副本
                activity = Activity.query.filter_by(name=activity_name).first()

                if activity:
                    # 檢查是否已存在此人
                    existing_participant = Participant.query.filter_by(
                        activity_id=activity.id,
                        user_name=new_participant_name
                    ).first()

                    if existing_participant:
                        response_text = f"➜{activity_name}：{new_participant_name} 已存在報名名單中"
                    else:
                        # 新增參與者
                        new_participant = Participant(
                            user_id=user_id,  # 使用當前操作用戶的ID
                            user_name=new_participant_name,
                            activity_id=activity.id
                        )
                        db.session.add(new_participant)
                        db.session.commit()

                        response_text = (
                            f"➜{activity_name}：{new_participant_name} 已成功報名\n"
                            f"副本時間：{activity.datetime}\n"
                            f"目前參加人數：{len(activity.participants)}"
                        )

                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                    messaging_api.reply_message(request)
                else:
                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"找不到名為 {activity_name} 的副本")]
                    )
                    messaging_api.reply_message(request)
            else:
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="指令格式錯誤。請使用：+ [副本名稱] [人員名稱]")]
                )
                messaging_api.reply_message(request)

        # 更新說明指令
        elif text == "說明":
            help_text = (
                "📝 指令說明\n"
                "-------------------\n"
                "1. 建立副本：\n"
                "➜ 副本 [副本名稱]\n"
                "例如：副本 打牌\n\n"
                "2. 查看副本列表：\n"
                "➜ 副本\n\n"
                "3. 副本功能：\n"
                "➜ 報名 - 參加副本\n"
                "➜ 取消 - 取消報名\n"
                "➜ 名單 - 查看報名名單\n"
                "➜ 移除 - 刪除副本(限創建者)\n"
                "➜ 刪除所有副本 - 清空所有副本列表 (需確認)\n"
                "➜ + [副本名稱] [人員名稱] - 新增特定人員到副本"
                "➜ - [副本名稱] [人員名稱] - 於副本名單中刪除特定人員"
            )
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=help_text)]
            )
            messaging_api.reply_message(request)

        elif text == "刪除所有副本":
            confirmation_message = FlexMessage(
                alt_text="確認刪除所有副本？",
                contents=FlexContainer.from_dict({
                   "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                         "contents": [
                            {
                                "type": "text",
                                "text": "確認刪除所有副本？",
                                "weight": "bold",
                                "size": "xl",
                                "align": "center"
                            },
                             {
                                "type": "separator",
                                "margin": "lg"
                            },
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "margin": "md",
                                "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "button",
                                        "style": "primary",
                                        "height": "sm",
                                         "action": {
                                            "type": "postback",
                                            "label": "是",
                                            "data": "action=confirm_delete_all"
                                            }
                                    },
                                    {
                                         "type": "button",
                                         "style": "secondary",
                                         "height": "sm",
                                         "action": {
                                              "type": "postback",
                                              "label": "否",
                                              "data": "action=cancel_delete_all"
                                          }
                                    }
                                ]
                             }
                         ]
                     }
                })
            )
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[confirmation_message]
            )
            messaging_api.reply_message(request)
            return

        elif text.startswith("➜ - "):
            parts = text.split(" ")
            if len(parts) == 4:  # 確保指令格式正確
                activity_name = parts[2]
                participant_name = parts[3]

                # 尋找副本
                activity = Activity.query.filter_by(name=activity_name).first()

                if activity:
                    # 尋找該參與者
                    participant = Participant.query.filter_by(
                        activity_id=activity.id,
                        user_name=participant_name
                    ).first()

                    if participant:
                        # 刪除參與者
                        db.session.delete(participant)
                        db.session.commit()

                        response_text = f"➜{activity_name}：{participant_name} 已從副本名單中刪除"
                    else:
                        response_text = f"➜{activity_name}：找不到 {participant_name} 的報名紀錄"

                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                    messaging_api.reply_message(request)
                else:
                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"找不到名為 {activity_name} 的副本")]
                    )
                    messaging_api.reply_message(request)
            else:
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="指令格式錯誤。請使用：➜ - [副本名稱] [人員名稱]")]
                )
                messaging_api.reply_message(request)

        elif text.startswith("副本 "):
            activity_name = text[3:].strip()
            if activity_name:
                user_states[user_id] = {
                    'step': 'datetime',
                    'name': activity_name
                }
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[create_datetime_picker_flex()]
                )
                messaging_api.reply_message(request)
            else:
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請輸入副本名稱，例如：副本 副本")]
                )
                messaging_api.reply_message(request)

        elif text == "副本":
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[create_activities_list_flex()]
            )
            messaging_api.reply_message(request)

    except Exception as e:
        logger.error(f"Error: {e}")

# Postback 事件處理器
@handler.add(PostbackEvent)
def handle_postback(event):
    """
    處理 LINE 互動按鈕的回調事件
    支援報名、取消報名、查看參與者、刪除副本等功能

    :param event: LINE Postback 事件
    """
    try:
        user_id = event.source.user_id
        data = event.postback.data

        # 副本建立流程
        if "action=select_date" in data:
            datetime_selected = event.postback.params['datetime']

            # 確認用戶狀態
            if user_id in user_states and user_states[user_id].get('step') == 'datetime':
                activity_name = user_states[user_id].get('name')

                if activity_name:
                    # 建立新的副本
                    new_activity = Activity(
                        name=activity_name,
                        datetime=datetime_selected,
                        creator_id=user_id
                    )
                    db.session.add(new_activity)
                    db.session.commit()

                    # 清除用戶狀態
                    del user_states[user_id]

                    response_message = create_activities_list_flex()
                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[response_message]
                    )
                    messaging_api.reply_message(request)

                else:
                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="副本創建失敗，請重新輸入")]
                    )
                    messaging_api.reply_message(request)
            else:
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="無法識別副本，請重新開始")]
                )
                messaging_api.reply_message(request)

        # 報名功能
        elif "action=join_activity" in data:
            # 允許用戶報名特定副本
            activity_id = int(data.split('&id=')[1])
            activity = Activity.query.get(activity_id)

            if activity:
                # 獲取用戶名稱
                try:
                    profile = messaging_api.get_profile(user_id)
                    user_name = profile.display_name
                except Exception as e:
                    logger.error(f"Error getting user profile: {e}")
                    user_name = user_id

                # 檢查是否已經報名
                existing_participant = Participant.query.filter_by(
                    activity_id=activity_id,
                    user_id=user_id
                ).first()

                if existing_participant:
                    response_text = f"➜{activity.name}：{user_name} 已報名"
                else:
                    # 建立新的參與者
                    new_participant = Participant(
                        user_id=user_id,
                        user_name=user_name,
                        activity_id=activity_id
                    )
                    db.session.add(new_participant)
                    db.session.commit()

                    response_text = (
                        f"➜{activity.name}：{user_name} 已成功報名\n"
                        f"副本時間：{activity.datetime}\n"
                        f"目前參加人數：{len(activity.participants)}"
                    )

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                messaging_api.reply_message(request)

        # 取消報名功能
        elif "action=cancel_join" in data:
            # 允許用戶取消報名特定副本
            activity_id = int(data.split('&id=')[1])
            activity = Activity.query.get(activity_id)

            if not activity:
                return

            # 獲取用戶名稱
            try:
                profile = messaging_api.get_profile(user_id)
                user_name = profile.display_name
            except Exception as e:
                logger.error(f"Error getting user profile: {e}")
                user_name = user_id

            # 檢查是否已報名
            participant = Participant.query.filter_by(
                activity_id=activity_id,
                user_id=user_id
            ).first()

            if participant:
                # 取消報名
                activity_name = participant.activity.name
                db.session.delete(participant)
                db.session.commit()
                response_text = f"➜{activity_name}：{user_name} 已取消報名"
            else:
                # 尚未報名
                response_text = f"➜{activity.name}：{user_name} 尚未報名"

            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response_text)]
            )
            messaging_api.reply_message(request)

        # 刪除副本功能
        elif "action=delete_activity" in data:
            # 允許創建者刪除特定副本
            activity_id = int(data.split('&id=')[1])
            activity = Activity.query.get(activity_id)

            if activity:
                if activity.creator_id == user_id:
                    activity_name = activity.name
                    Participant.query.filter_by(activity_id=activity_id).delete()
                    db.session.delete(activity)
                    db.session.commit()
                    response_text = f"➜{activity_name}：已刪除"
                else:
                    try:
                        profile = messaging_api.get_profile(user_id)
                        user_name = profile.display_name
                    except:
                        user_name = user_id
                    response_text = f"➜{activity.name}：{user_name} 無刪除權限"

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                messaging_api.reply_message(request)

        # 查看參與者名單
        elif "action=view_participants" in data:
            # 顯示特定副本的參與者名單
            activity_id = int(data.split('&id=')[1])
            activity = Activity.query.get(activity_id)

            if activity:
                participant_list = '\n'.join([
                    f"✓ {p.user_name}" for p in activity.participants
                ])

                response_text = (
                    f"➜{activity.name} 報名名單\n"
                    f"副本時間：{activity.datetime}\n"
                    f"參加人數：{len(activity.participants)}人\n"
                    f"-----------------\n"
                    f"{participant_list}"
                )

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                messaging_api.reply_message(request)

        # 確認/取消刪除所有副本
        elif "action=confirm_delete_all" in data:
            # 刪除所有副本和參與者記錄
            Participant.query.delete()
            Activity.query.delete()
            db.session.commit()
            response_text = "所有副本已刪除"
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response_text)]
            )
            messaging_api.reply_message(request)

        elif "action=cancel_delete_all" in data:
            response_text = "已取消刪除所有副本"
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response_text)]
            )
            messaging_api.reply_message(request)

    except Exception as e:
        logger.error(f"Error in handle_postback: {e}")



# 修改初始化數據庫的函數
def init_db():
    """
    初始化應用程式資料庫
    創建所有定義的資料庫表格
    """
    with app.app_context():
        db.create_all()
        print("Database initialized")

# 主程式入口
if __name__ == "__main__":
    # 初始化資料庫
    with app.app_context():
       init_db()

    # 從環境變數獲取運行端口，預設為 5000
    port = int(os.environ.get('PORT', 5000))

    # 啟動 Flask 應用程式
    app.run(host='0.0.0.0', port=port)