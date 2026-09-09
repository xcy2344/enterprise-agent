import requests

url = "http://localhost:8000/api/v1/agent"

# 第一次请求：告诉系统你的偏好
data1 = {"question": "我喜欢喝冰咖啡", "user_id": "user_001"}
response1 = requests.post(url, json=data1)
print("第一次:", response1.json())

# 第二次请求：看系统是否还记得
data2 = {"question": "你记得我喜欢喝什么吗", "user_id": "user_001"}
response2 = requests.post(url, json=data2)
print("第二次:", response2.json())