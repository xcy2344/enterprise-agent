import requests

url = "http://localhost:8000/api/v1/chat"
data = {"question": "年假怎么申请"}

response = requests.post(url, json=data)
print(response.status_code)
print(response.json())