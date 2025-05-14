import json
import threading
import time
import socket
from datetime import datetime, timedelta
from flask import Flask, request, abort, jsonify, render_template
from flask_socketio import SocketIO, emit
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (MessageEvent, PostbackEvent, TextMessage, TextSendMessage, TemplateSendMessage,
                            ButtonsTemplate, PostbackAction, CarouselTemplate, CarouselColumn)


import tinytuya
# 智慧插座配置

# 實體插座
# PLUGID = 'eb5a0e6ff8a8c3e3d8o9ju'
# PLUGIP = '140.117.187.57'

# 虛擬插座
PLUGID = 'vdevo171411666146254'
PLUGIP = '223.139.113.10'

PLUGKEY = ":#/4!IE;'&42~g;r"
PLUGVERS = '3.5'
REGION = "us"
APIKEY = "q9pwjs9rw4599kvngq8m"
APISEC = "23ff10ff20ce4b23a8a97b5dbb2bb2c1"
plug = tinytuya.Cloud(REGION, APIKEY, APISEC, PLUGID)

app = Flask(__name__)
socketio = SocketIO(app)

# Line Bot 配置
LINE_CHANNEL_ACCESS_TOKEN = 'XCMjONp1iAFSQF52JAptsj/yHIU25UyrK3406wUgv0od9aS+yExmGsCtDC98LXe2GrmAYPpsIRX+yfVqDATTlk00RHfBLWBDJcwM0oa/8zVf+Bgj6QKrTVdJTZ1zOdSCbGxavrLDfdgcTP0Xt+FHnAdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '23aa7751a5688eead7b53c7a29a65614'
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化計時器
last_state = {
    "plug": 0,
    "1FA": 0, "1FB": 0,
    "2FA": 0, "2FB": 0,
    "3FA": 0, "3FB": 0
}
x_timestamp = {key: None for key in last_state}
y_timestamp = {key: None for key in last_state}
remaining_times = {key: 0 for key in last_state}  # 用來保存每個計時器的剩餘時間
counter_file = 'counter.json'
# 設置 plug 的 z_duration 為 40 分鐘
z_duration_plug = 40 * 60  # 40 分鐘的秒數

# 存儲用戶通知設置的字典
notify = {}

def get_wash_state(timer_name):
    if timer_name == "plug":
        # 智慧插座的處理邏輯
        result = plug.getstatus(PLUGID)
        # 以即時功率 5W 為分界判斷串接了智慧插座的洗衣機是否開啟
        return 1 if result["result"][4]["value"] >= 50 else 0
    else:
        # 其他計時器的處理邏輯
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('localhost', 65432))
                s.sendall(timer_name.encode('utf-8'))
                data = s.recv(1024).decode('utf-8')
                return int(data)
        except Exception as e:
            print(f"Error connecting to tkinter_test_counter: {e}")
            return -1

def update_timer_in_file(timer_name, duration):
    try:
        with open(counter_file, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    data[timer_name] = {"duration": duration}

    with open(counter_file, 'w') as f:
        json.dump(data, f, indent=4)

# 推送洗衣完成通知
def notify_users(timer_name):
    floor_mapping = {
        "plug": "測試智慧插座", 
        "1FA": "1樓A", "1FB": "1樓B",
        "2FA": "2樓A", "2FB": "2樓B",
        "3FA": "3樓A", "3FB": "3樓B"
    }

    floor_name = floor_mapping.get(timer_name, timer_name)
    users_to_notify = []

    # 查找所有開啟了該計時器通知的用戶
    for user_id, settings in notify.items():
        if settings.get(floor_name) == 1:  # 檢查該用戶是否開啟該計時器的通知
            users_to_notify.append(user_id)

    # 推送通知給所有開啟通知的用戶
    for user_id in users_to_notify:
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=f"{floor_name} 已完成洗衣。")
            )
            # 成功推送後，重置該用戶的通知狀態
            notify[user_id][floor_name] = 0  # 重設通知狀態
        except Exception as e:
            print(f"Error pushing message to user {user_id}: {e}")


def record_state(timer_name):
    global last_state, x_timestamp, y_timestamp

    z_duration = z_duration_plug if timer_name == "plug" else 10  # plug 專用 40 分鐘計時器

    while True:
        current_state = get_wash_state(timer_name)
        current_time = datetime.now()

        if last_state[timer_name] is not None:
            # 計時器從 1 -> 0，即倒數結束時
            if last_state[timer_name] == 1 and current_state == 0:
                y_timestamp[timer_name] = current_time
                if x_timestamp[timer_name]:
                    duration = (y_timestamp[timer_name] - x_timestamp[timer_name]).total_seconds()
                    update_timer_in_file(timer_name, duration)
                    # 推送訊息給開啟通知的使用者
                    notify_users(timer_name)
                socketio.emit('timer_update', {"timer": timer_name, "message": "待機中"})
                remaining_times[timer_name] = 0  # 計時器進入待機狀態
            elif last_state[timer_name] == 0 and current_state == 1:
                x_timestamp[timer_name] = current_time
                socketio.emit('timer_update', {"timer": timer_name, "message": "開始倒數"})

        if current_state == 1 and x_timestamp[timer_name]:
            remaining_time = (x_timestamp[timer_name] + timedelta(seconds=z_duration)) - current_time

            if timer_name == "plug":  # Plug 計時器，顯示剩餘分鐘數
                remaining_minutes = remaining_time.total_seconds() / 60
                if remaining_minutes < 1:
                    remaining_message = "不到1分鐘"
                else:
                    remaining_message = f"{int(remaining_minutes)} 分鐘"
                remaining_times[timer_name] = int(remaining_minutes)  # 更新 plug 的剩餘分鐘數
            else:  # 其他計時器，顯示剩餘秒數
                remaining_seconds = int(remaining_time.total_seconds())
                remaining_message = f"{remaining_seconds} 秒"
                remaining_times[timer_name] = remaining_seconds  # 更新其他計時器的剩餘秒數

            # 更新網頁前端
            socketio.emit('timer_update', {"timer": timer_name, "message": remaining_message})

        last_state[timer_name] = current_state
        time.sleep(5 if timer_name == "plug" else 1)  # plug 的迴圈每 5 秒執行一次


# Line Bot Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# Line 訊息處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text

    if user_message == "設定通知":
        line_bot_api.reply_message(
            event.reply_token,
            create_carousel_template(event.source.user_id)
        )
    elif user_message == "查詢通知":
        reply_notify_settings(event.source.user_id, event.reply_token)
    elif user_message.startswith("查詢"):
        reply_remaining_time(user_message, event.reply_token)

# 創建 Carousel Template，讓使用者啟用或關閉測試智慧插座的通知
def create_carousel_template(user_id):
    columns = []
    floors = ["測試智慧插座", "1樓A", "1樓B", "2樓A", "2樓B", "3樓A", "3樓B"]

    for floor in floors:
        columns.append(
            CarouselColumn(
                text=f"{floor} 的通知設定",
                actions=[
                    PostbackAction(label="開啟通知", data=f"enable_{floor}_{user_id}"),
                    PostbackAction(label="關閉通知", data=f"disable_{floor}_{user_id}")
                ]
            )
        )

    carousel_template = TemplateSendMessage(
        alt_text='設定通知',
        template=CarouselTemplate(columns=columns)
    )
    return carousel_template

# 回覆當前已啟用的通知設置，plug 排在 1樓A 前面
def reply_notify_settings(user_id, reply_token):
    if user_id not in notify or not notify[user_id]:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="未開啟任何洗衣結束通知。如需開啟通知，請輸入「設定通知」")
        )
        return

    # 預設的樓層順序，plug 排在 1樓A 前面
    sorted_floors = ["測試智慧插座", "1樓A", "1樓B", "2樓A", "2樓B", "3樓A", "3樓B"]

    # 收集已開啟通知的樓層
    enabled_notifications = [floor for floor in sorted_floors if notify[user_id].get(floor) == 1]

    if enabled_notifications:
        # 使用換行符號進行分隔，並以固定排序回覆已開啟的通知
        response_message = "已啟用之洗衣結束通知：\n" + "\n".join(enabled_notifications)
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=response_message)
        )
    else:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="未開啟任何洗衣結束通知。如需開啟通知，請輸入「設定通知」")
        )

def reply_remaining_time(user_message, reply_token):
    floors = {
        "測試智慧插座": "plug",  # plug 計時器
        "1樓A": "1FA", "1樓B": "1FB",
        "2樓A": "2FA", "2樓B": "2FB",
        "3樓A": "3FA", "3樓B": "3FB"
    }

    if user_message == "查詢所有時間":
        messages = []
        for floor, timer in floors.items():
            if last_state[timer] == 0:  # 計時器為待機中
                messages.append(f"{floor}: 待機中")
            else:
                if timer == "plug":
                    if remaining_times[timer] < 1:
                        messages.append(f"{floor}: 不到1分鐘")
                    else:
                        messages.append(f"{floor}: {remaining_times[timer]} 分鐘")
                else:
                    messages.append(f"{floor}: {remaining_times[timer]} 秒")

        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="\n".join(messages))
        )

    elif user_message in ["查詢1樓", "查詢2樓", "查詢3樓"]:
        floor_num = user_message[-2] + "樓"  # 修正索引，正確取得樓層號
        messages = []
        for floor, timer in floors.items():
            if floor.startswith(floor_num):  # 正確篩選指定樓層
                if last_state[timer] == 0:  # 計時器為待機中
                    messages.append(f"{floor}: 待機中")
                else:
                    if timer == "plug":
                        if remaining_times[timer] < 1:
                            messages.append(f"{floor}: 不到1分鐘")
                        else:
                            messages.append(f"{floor}: {remaining_times[timer]} 分鐘")
                    else:
                        messages.append(f"{floor}: {remaining_times[timer]} 秒")

        if messages:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="\n".join(messages))
            )
        else:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="無可查詢的洗衣機資訊。")
            )

    else:
        specific_timer = user_message.replace("查詢", "")
        if specific_timer in floors:
            timer_key = floors[specific_timer]
            if last_state[timer_key] == 0:  # 計時器為待機中
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text=f"{specific_timer}: 待機中")
                )
            elif specific_timer == "plug":
                if remaining_times[timer_key] < 1:
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(text=f"{specific_timer}: 不到1分鐘")
                    )
                else:
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(text=f"{specific_timer}: {remaining_times[timer_key]} 分鐘")
                    )
            else:
                line_bot_api.reply_message(
                    reply_token,
                    TextSendMessage(text=f"{specific_timer}: {remaining_times[timer_key]} 秒")
                )
        else:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="無法查詢該洗衣機。")
            )

# Line Postback 處理
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data.split('_')
    action = data[0]
    floor = data[1]
    user_id = data[2]

    if user_id not in notify:
        notify[user_id] = {}

    if action == "enable":
        notify[user_id][floor] = 1
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"已設定 {floor} 的通知，洗衣完成時您將會收到通知。")
        )
    elif action == "disable":
        notify[user_id][floor] = 0
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"已關閉 {floor} 的通知，洗衣完成時您不會收到通知。")
        )


@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # 啟動計時器
    timers = ["plug", "1FA", "1FB", "2FA", "2FB", "3FA", "3FB"]
    for timer in timers:
        threading.Thread(target=record_state, args=(timer,), daemon=True).start()
    socketio.run(app, debug=True)
