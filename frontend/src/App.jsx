import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

// 后端接口地址（本地 FastAPI 服务）
const API_BASE = 'http://localhost:8000'
const KNOWLEDGE_LIST_URL = `${API_BASE}/api/v1/admin/knowledge/list`
const AGENT_STREAM_URL = `${API_BASE}/api/v1/agent/stream`

// 后端不可用时的统一提示
const CONNECT_ERROR = '服务连接失败，请确认后端已启动'

// 流正常结束但没有任何内容时的兜底提示
const EMPTY_REPLY = '（未收到回复内容）'

/**
 * 读取（或生成）本机用户 ID，保存在 localStorage 中
 * 同一个浏览器多轮对话复用同一个 user_id，后端才能用会话级短期记忆联系上下文
 */
function getOrCreateUserId() {
  const STORAGE_KEY = 'kb_agent_user_id'
  let userId = localStorage.getItem(STORAGE_KEY)
  if (!userId) {
    // crypto.randomUUID 需要安全上下文，http://localhost 满足；否则退回时间戳方案
    userId = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `user_${Date.now()}_${Math.floor(Math.random() * 1000000)}`
    localStorage.setItem(STORAGE_KEY, userId)
  }
  return userId
}

export default function App() {
  const [messages, setMessages] = useState([])               // 对话历史：{ role, content }
  const [input, setInput] = useState('')                     // 输入框内容
  const [sending, setSending] = useState(false)              // 是否正在流式接收
  const [items, setItems] = useState([])                     // 知识库条目列表
  const [total, setTotal] = useState(0)                      // 知识库条目数量
  const [showKnowledge, setShowKnowledge] = useState(false)  // 是否弹出知识库列表
  const [error, setError] = useState('')                     // 错误提示

  const messagesRef = useRef(null)                // 消息区容器（用于自动滚到底部）
  const userIdRef = useRef(getOrCreateUserId())   // 会话 ID，整个页面生命周期内只取一次

  // 页面加载时拉取知识库列表，用于显示条目数量
  useEffect(() => {
    let cancelled = false

    async function loadKnowledge() {
      try {
        const res = await fetch(KNOWLEDGE_LIST_URL)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (cancelled) return
        const list = Array.isArray(data.items) ? data.items : []
        setItems(list)
        setTotal(typeof data.total === 'number' ? data.total : list.length)
      } catch {
        if (!cancelled) setError(CONNECT_ERROR)
      }
    }

    loadKnowledge()
    return () => { cancelled = true }
  }, [])

  // 有新消息时自动滚动到底部
  useEffect(() => {
    const el = messagesRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  /**
   * 把一段文本追加到「最后一条 AI 消息」上，实现打字机效果
   */
  const appendToAssistant = useCallback((chunk) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (!last || last.role !== 'assistant') return prev
      const next = prev.slice(0, -1)
      next.push({ role: 'assistant', content: last.content + chunk })
      return next
    })
  }, [])

  /**
   * 替换最后一条 AI 消息的内容（用于失败兜底提示）
   */
  const replaceAssistant = useCallback((text) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (!last || last.role !== 'assistant') return prev
      const next = prev.slice(0, -1)
      next.push({ role: 'assistant', content: text })
      return next
    })
  }, [])

  /**
   * 发送问题：POST /api/v1/agent/stream，逐块读取 SSE 数据
   * SSE 格式：data: {"content": "..."}\n\n，结束时下发 data: [DONE]
   */
  async function handleSend() {
    const question = input.trim()
    if (!question || sending) return

    setError('')
    setInput('')
    setSending(true)
    // 先插入用户消息和一条空的 AI 消息，流式内容会不断追加到这条 AI 消息上
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '' },
    ])

    try {
      const res = await fetch(AGENT_STREAM_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, user_id: userIdRef.current }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let finished = false

      while (!finished) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // 按行解析；最后一行可能不完整，留到下一次读取再拼
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const payload = line.slice(5).trim()
          if (payload === '[DONE]') {   // 流结束标记
            finished = true
            break
          }
          if (!payload) continue
          try {
            const data = JSON.parse(payload)
            if (data.content) appendToAssistant(data.content)
          } catch {
            // 解析失败的行直接忽略，不影响后续内容
          }
        }
      }
      if (finished) await reader.cancel()
    } catch {
      // 后端未启动 / 网络异常：给出统一提示
      setError(CONNECT_ERROR)
      replaceAssistant(CONNECT_ERROR)
    } finally {
      setSending(false)
      // 处理「流结束但没有任何内容」的情况
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (!last || last.role !== 'assistant' || last.content) return prev
        const next = prev.slice(0, -1)
        next.push({ role: 'assistant', content: EMPTY_REPLY })
        return next
      })
    }
  }

  // 回车发送（中文输入法组合中不触发）
  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
      event.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="app">
      {/* 顶部标题栏 */}
      <header className="header">智核 · 企业知识 MCP 中枢</header>

      <div className="body">
        {/* 左侧边栏 */}
        <aside className="sidebar">
          <div className="sidebar-block">
            <div className="kb-count">知识库条目：{total} 条</div>
            <button
              className="btn"
              onClick={() => setShowKnowledge((prev) => !prev)}
            >
              查看知识库
            </button>
          </div>
          <div className="sidebar-footer">
            基于 RAG 的企业知识库问答 Agent：Planner 任务规划、工具调用、多轮记忆与流式输出。
          </div>
        </aside>

        {/* 主区域：对话历史 + 底部输入框 */}
        <main className="chat">
          {error && <div className="error-bar">{error}</div>}

          <div className="messages" ref={messagesRef}>
            {messages.length === 0 && (
              <div className="empty-tip">
                试试问：「年假怎么申请？」「报销流程是什么？」
              </div>
            )}
            {messages.map((msg, index) => (
              <div
                key={index}
                className={`row ${msg.role === 'user' ? 'row-user' : 'row-ai'}`}
              >
                <div className={`bubble ${msg.role === 'user' ? 'bubble-user' : 'bubble-ai'}`}>
                  {msg.content || (sending ? '正在思考…' : '')}
                </div>
              </div>
            ))}
          </div>

          <div className="composer">
            <input
              className="input"
              type="text"
              value={input}
              placeholder="输入你的问题，回车发送"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={sending}
            />
            <button className="btn btn-send" onClick={handleSend} disabled={sending}>
              {sending ? '生成中…' : '发送'}
            </button>
          </div>
        </main>
      </div>

      {/* 知识库列表弹层 */}
      {showKnowledge && (
        <div className="modal-mask" onClick={() => setShowKnowledge(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span>知识库条目（共 {total} 条）</span>
              <button className="btn btn-close" onClick={() => setShowKnowledge(false)}>
                关闭
              </button>
            </div>
            <div className="modal-body">
              {items.length === 0 && <div className="empty-tip">暂无知识条目</div>}
              {items.map((item) => (
                <div className="kb-item" key={item.id}>
                  <div className="kb-item-text">{item.text}</div>
                  <div className="kb-item-source">来源：{item.source || '未知'}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
