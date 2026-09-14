import requests

url = "http://localhost:8000/api/v1/admin/knowledge/add"

# 先获取已有知识
list_url = "http://localhost:8000/api/v1/admin/knowledge/list"
response = requests.get(list_url)
existing = response.json().get("items", [])
existing_texts = [item["text"] for item in existing]
print(f"已有 {len(existing_texts)} 条知识")

# 要添加的知识列表
new_items = [
    {"text": "加班需要提前申请，经部门经理审批后方可计算加班费。工作日加班按1.5倍工资计算，周末按2倍计算。", "source": "policy.md"},
    {"text": "病假需要提供医院证明，年假需要提前3个工作日申请，事假需要提前1天申请。所有请假均需在飞书上提交申请。", "source": "policy.md"},
    {"text": "新员工入职需要准备身份证、银行卡、学历学位证书原件及复印件、离职证明、一寸照片2张。入职当天签订劳动合同。", "source": "onboarding.md"},
    {"text": "新员工入职后需参加为期3天的入职培训，包含公司文化、制度流程、业务知识等内容。培训结束需通过考核。", "source": "training.md"},
    {"text": "报销单提交后，部门经理需在48小时内审批，财务部在收到审批通过的单据后5个工作日内完成打款。单笔5000元以上需CFO审批。", "source": "finance.md"},
    {"text": "出差需提前填写出差申请单，注明出差地点、时间、事由、预算。差旅费标准：住宿费500元/天，餐补150元/天，交通费实报实销。", "source": "travel.md"},
    {"text": "公司提供五险一金、补充医疗保险、年度体检、节日福利、生日福利、团建经费等。其中五险一金按全额工资缴纳。", "source": "benefits.md"},
    {"text": "考勤记录以飞书打卡为准。迟到30分钟以内算迟到，超过30分钟算旷工半天。每月累计旷工超过2天，取消当月绩效奖金。", "source": "attendance.md"},
    {"text": "办公用品申请在飞书审批中提交，注明名称、数量、用途。普通办公用品1个工作日内审批完成，电脑等设备3个工作日内审批完成。", "source": "office.md"},
]

added = 0
skipped = 0
for item in new_items:
    if item["text"] in existing_texts:
        print(f"[SKIP] 跳过已存在: {item['text'][:30]}...")
        skipped += 1
        continue
    resp = requests.post(url, json=item)
    if resp.status_code == 200:
        print(f"[OK] 添加成功: {item['text'][:30]}...")
        added += 1
    else:
        print(f"[ERROR] 添加失败: {item['text'][:30]}...")

print(f"\n[INFO] 完成：新增 {added} 条，跳过 {skipped} 条（已存在）")
