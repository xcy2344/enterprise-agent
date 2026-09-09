from app.core.agent_loop import AgentLoop

agent = AgentLoop()
user_id = "test_user"

# 第一次：告诉 Agent 你的偏好
print("=" * 50)
print("第一次：告诉 Agent 你喜欢喝冰咖啡")
result1 = agent.run("我喜欢喝冰咖啡", user_id)
print("回答:", result1["answer"])
print("动作:", result1["action"])

# 第二次：问 Agent 是否记得
print("\n" + "=" * 50)
print("第二次：问 Agent 是否记得")
result2 = agent.run("你记得我喜欢喝什么吗", user_id)
print("回答:", result2["answer"])
print("动作:", result2["action"])