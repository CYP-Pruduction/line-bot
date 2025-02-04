# line_app.py
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

app = Flask(__name__)

# 環境變數配置
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://')

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# LINE Bot 設定從環境變數獲取
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')

configuration = Configuration(access_token=channel_access_token)
api_client = ApiClient(configuration)
messaging_api = MessagingApi(api_client)
handler = WebhookHandler(channel_secret)

# Database Models
class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(30), nullable=False)
    time = db.Column(db.String(30), nullable=False)
    creator_id = db.Column(db.String(50), nullable=False)
    participants = db.relationship('Participant', backref='activity', lazy=True)


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    user_name = db.Column(db.String(100))
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)


# 使用者狀態追蹤
user_states = {}


async def get_user_profile(user_id):
    """獲取 LINE 用戶資料"""
    try:
        profile = await messaging_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return "未知用戶"

def run_async(coro):
    """協助執行非同步函數的輔助函數"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def create_activity_name_input():
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


def create_activities_list_flex():
    activities = Activity.query.all()

    if not activities:
        return TextMessage(text="目前沒有任何副本")

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
                "text": f"日期: {activity.date}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"時間: {activity.time}",
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


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        logger.error(f"Error: {e}")
    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    try:
        user_id = event.source.user_id
        text = event.message.text

        # 處理刪除所有副本的命令
        if text == "刪除所有副本":
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

        # 處理新增人員指令
        if text.startswith("+ "):
            parts = text.split(" ")
            if len(parts) == 3:
                activity_name = parts[1]
                new_participant_name = parts[2]

                activity = Activity.query.filter_by(name=activity_name).first()

                if activity:
                    existing_participant = Participant.query.filter_by(
                        activity_id=activity.id,
                        user_name=new_participant_name
                    ).first()

                    if existing_participant:
                        response_text = f"➜{activity_name}：{new_participant_name} 已存在報名名單中"
                    else:
                        new_participant = Participant(
                            user_id=user_id,
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

        # 處理說明指令
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
                "➜ + [副本名稱] [人員名稱] - 新增特定人員到副本\n"
                "➜ - [副本名稱] [人員名稱] - 於副本名單中刪除特定人員"
            )
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=help_text)]
            )
            messaging_api.reply_message(request)

        # 處理刪除特定人員指令
        elif text.startswith("➜ - "):
            parts = text.split(" ")
            if len(parts) == 4:
                activity_name = parts[2]
                participant_name = parts[3]

                activity = Activity.query.filter_by(name=activity_name).first()

                if activity:
                    participant = Participant.query.filter_by(
                        activity_id=activity.id,
                        user_name=participant_name
                    ).first()

                    if participant:
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

        # 處理建立副本指令
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

        # 處理查看副本列表指令
        elif text == "副本":
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[create_activities_list_flex()]
            )
            messaging_api.reply_message(request)

    except Exception as e:
        logger.error(f"Error in handle_text_message: {e}", exc_info=True)
        # 發送錯誤消息給用戶
        request = ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="處理您的請求時發生錯誤，請稍後再試。")]
        )
        messaging_api.reply_message(request)


@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        user_id = event.source.user_id
        data = event.postback.data

        # 副本建立流程
        if "action=select_date" in data and hasattr(event.postback, 'params'):
            datetime_selected = event.postback.params.get('datetime')
            logger.info(f"Received datetime_selected: {datetime_selected}")

            # 檢查用戶狀態
            user_state = user_states.get(user_id)
            if not user_state:
                logger.error(f"找不到使用者 {user_id} 的狀態")
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請重新開始建立副本流程")]
                )
                messaging_api.reply_message(request)
                return

            # 確認用戶狀態和活動名稱

            if not user_state or 'name' not in user_state:
                logger.error(f"使用者 {user_id} 的狀態無效")
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請重新開始建立副本流程")]
                )
                messaging_api.reply_message(request)
                return

            activity_name = user_state.get('name')

            # 檢查活動名稱是否存在
            if not activity_name:
                logger.error("活動名稱遺失")
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="副本名稱無效，請重新輸入")]
                )
                messaging_api.reply_message(request)
                return

            try:
                # 檢查是否已存在相同名稱的副本
                existing_activity = Activity.query.filter_by(name=activity_name).first()
                if existing_activity:
                    logger.info(f"名為 {activity_name} 的副本已存在")
                    response_text = f"已存在名為 {activity_name} 的副本"
                    request = ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                    messaging_api.reply_message(request)
                    return

                # 將日期時間字串轉換為 datetime 物件
                dt_object = datetime.strptime(datetime_selected, '%Y-%m-%dT%H:%M')

                # 提取日期和時間
                date_selected = dt_object.strftime('%Y-%m-%d')
                time_selected = dt_object.strftime('%H:%M')

                # 建立新的副本
                new_activity = Activity(
                    name=activity_name,
                    date=date_selected,
                    time=time_selected,
                    creator_id=user_id
                )
                db.session.add(new_activity)
                db.session.commit()

                # 清除用戶狀態
                del user_states[user_id]

                # 顯示副本列表
                activities_list = create_activities_list_flex()

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[activities_list]
                )

            except Exception as e:
                logger.error(f"建立副本時發生資料庫錯誤：{str(e)}", exc_info=True)
                db.session.rollback()
                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="建立副本時發生錯誤，請稍後再試")]
                )
                messaging_api.reply_message(request)
                return

        # 報名功能
        elif "action=join_activity" in data:
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

        # 保留其他原有的 postback 處理邏輯
        elif "action=delete_activity" in data:
            # (原有的刪除副本邏輯)
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

        # 其他原有的 postback 處理（如查看參與者、刪除所有副本等）
        elif "action=view_participants" in data:
            # (原有的查看參與者邏輯)
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

        # 刪除所有副本相關的 postback
        elif "action=confirm_delete_all" in data:
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
        logger.error(f"handle_postback 發生未預期錯誤：{str(e)}", exc_info=True)
        try:
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="處理請求時發生錯誤，請稍後再試。")]
            )
            messaging_api.reply_message(request)
        except Exception as reply_error:
            logger.error(f"發送錯誤訊息時發生錯誤：{str(reply_error)}")

# 修改初始化數據庫的函數
def init_db():
    with app.app_context():
        db.drop_all()  # 先刪除所有表格
        db.create_all()
        print("Database initialized")

if __name__ == "__main__":
    with app.app_context():
       init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)