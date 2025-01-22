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
    datetime = db.Column(db.String(30), nullable=False)
    creator_id = db.Column(db.String(50), nullable=False)  # 新增創建者 ID
    participants = db.relationship('Participant', backref='activity', lazy=True)


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    user_name = db.Column(db.String(100))
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)


# 使用者狀態追蹤
user_states = {}


def get_user_profile(user_id):
    """獲取 LINE 用戶資料"""
    try:
        profile = messaging_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return "未知用戶"


def create_select_activity_and_datetime_flex(user_id):
    selected_activity = user_states.get(user_id, {}).get('name', None)

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
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "secondary" if selected_activity == "舞陽城" else "primary",
                             "flex": 1,
                            "action": {
                                "type": "postback",
                                "label": f"{'✓ ' if selected_activity == '舞陽城' else ''}舞陽城",
                                "data": "action=select_activity&name=舞陽城"
                            }
                         },
                        {
                             "type": "button",
                             "style": "secondary" if selected_activity == "劍夢武林" else "primary",
                             "flex": 1,
                             "action": {
                                "type": "postback",
                                "label": f"{'✓ ' if selected_activity == '劍夢武林' else ''}劍夢武林",
                                "data": "action=select_activity&name=劍夢武林"
                            }
                         }
                    ]
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
        alt_text="選擇副本名稱和時間",
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
                "text": f"時間: {activity.datetime}",
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

        if text == "說明":
            help_text = (
                "📝 指令說明\n"
                "-------------------\n"
                "1. 建立副本：\n"
                "➜ +副本\n\n"
                "2. 查看副本列表：\n"
                "➜ 副本\n\n"
                 "3. 副本功能：\n"
                "➜ 報名 - 參加副本\n"
                "➜ 取消 - 取消報名\n"
                "➜ 名單 - 查看報名名單\n"
                "➜ 移除 - 刪除副本(限創建者)\n"
            )
            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=help_text)]
            )
            messaging_api.reply_message(request)
        elif text == "+副本":
             request = ReplyMessageRequest(
                 reply_token=event.reply_token,
                 messages=[create_select_activity_and_datetime_flex(event.source.user_id)]
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


def get_user_profile(user_id):
    """獲取 LINE 用戶資料"""
    try:
        profile = messaging_api.get_profile(user_id)
        return profile.display_name
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return "未知用戶"

@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        user_id = event.source.user_id
        data = event.postback.data

        if "action=select_activity" in data:
             activity_name = data.split('&name=')[1]
             if user_id not in user_states:
                user_states[user_id] = {}
             if user_states[user_id].get('name') == activity_name:
                user_states[user_id].pop('name',None)
             else:
                user_states[user_id]['name'] = activity_name
             request = ReplyMessageRequest(
                 reply_token=event.reply_token,
                 messages=[create_select_activity_and_datetime_flex(user_id)]
             )
             messaging_api.reply_message(request)

        elif "action=select_date" in data:
            if user_id in user_states and 'name' in user_states[user_id]:
                new_activity = Activity(
                    name=user_states[user_id]['name'],
                    datetime=event.postback.params['datetime'],
                    creator_id=user_id
                )
                db.session.add(new_activity)
                db.session.commit()

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[create_activities_list_flex()]
                )
                messaging_api.reply_message(request)

                del user_states[user_id]
            else:
               request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="請先選擇副本名稱")]
                )
               messaging_api.reply_message(request)


        elif "action=join_activity" in data:
            activity_id = int(data.split('&id=')[1])
            activity = Activity.query.get(activity_id)

            if activity:
                existing_participant = Participant.query.filter_by(
                    activity_id=activity_id,
                    user_id=user_id
                ).first()
                user_name = get_user_profile(user_id)

                if existing_participant:
                    response_text = f"➜{activity.name}：{user_name} 已報名"
                else:
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
                        f"參加人數：{len(activity.participants)}"
                    )

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                messaging_api.reply_message(request)

        elif "action=cancel_join" in data:
            activity_id = int(data.split('&id=')[1])
            activity = Activity.query.get(activity_id)

            if not activity:
                return

            participant = Participant.query.filter_by(
                activity_id=activity_id,
                user_id=user_id
            ).first()

            user_name = get_user_profile(user_id)

            if participant:
                activity_name = participant.activity.name
                db.session.delete(participant)
                db.session.commit()
                response_text = f"➜{activity_name}：{user_name} 已取消"
            else:
                response_text = f"➜{activity.name}：{user_name} 尚未報名"

            request = ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response_text)]
            )
            messaging_api.reply_message(request)

        elif "action=delete_activity" in data:
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
                    user_name = get_user_profile(user_id)
                    response_text = f"➜{activity.name}：{user_name} 無刪除權限"

                request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                messaging_api.reply_message(request)

        elif "action=view_participants" in data:
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

    except Exception as e:
        logger.error(f"Error: {e}")

# 修改初始化數據庫的函數
def init_db():
    with app.app_context():
        db.create_all()
        print("Database initialized")

if __name__ == "__main__":
    with app.app_context():
       init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)