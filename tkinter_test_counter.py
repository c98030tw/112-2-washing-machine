import tkinter as tk
import threading
import time
import socket

# 初始化視窗
root = tk.Tk()
root.title("Wash State Controller")

# 設置視窗的預設尺寸 400x300
root.geometry('400x300')

# 宣告 current_wash_state 字典
current_wash_state = {
    "1FA": 0, "1FB": 0,
    "2FA": 0, "2FB": 0,
    "3FA": 0, "3FB": 0
}

# 當按下按鈕後開始倒數的函式
def start_countdown(wash_name, button):
    button.config(state=tk.DISABLED)
    current_wash_state[wash_name] = 1
    button.config(text=f"{wash_name} 倒數中...")
    time.sleep(10)
    current_wash_state[wash_name] = 0
    button.config(state=tk.NORMAL)
    button.config(text="開始倒數")

# 動態生成按鈕
def create_button(wash_name, row):
    button = tk.Button(root, text="開始倒數", command=lambda: threading.Thread(target=start_countdown, args=(wash_name, button)).start())
    button.grid(row=row, column=1, padx=20, pady=10)
    label = tk.Label(root, text=wash_name)
    label.grid(row=row, column=0, padx=20, pady=10)

# 建立6個按鈕和標籤
create_button("1FA", 0)
create_button("1FB", 1)
create_button("2FA", 2)
create_button("2FB", 3)
create_button("3FA", 4)
create_button("3FB", 5)

# Socket 伺服器部分
def socket_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('localhost', 65432))
    server_socket.listen()
    while True:
        client_socket, addr = server_socket.accept()
        with client_socket:
            data = client_socket.recv(1024).decode('utf-8')
            if data in current_wash_state:
                response = str(current_wash_state[data])
            else:
                response = '-1'
            client_socket.sendall(response.encode('utf-8'))

# 啟動 Socket 伺服器的執行緒
socket_thread = threading.Thread(target=socket_server, daemon=True)
socket_thread.start()

# 啟動 Tkinter 視窗
root.mainloop()
