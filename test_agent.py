import requests

url = "http://localhost:8000/api/v1/agent"
data = {"question": "年假怎么申请", "user_id": "test_user"}

response = requests.post(url, json=data)
print("状态码:", response.status_code)
print("返回结果:", response.json())
