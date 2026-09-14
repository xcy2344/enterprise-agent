from app.core.vector_store import vector_store
from app.utils.logger import logger


def load_knowledge():
    """加载知识文档到向量库"""
    file_path = "data/knowledge/policies.txt"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        logger.error("知识文件不存在，请检查路径")
        return

    # 按空行切分成段落
    chunks = [chunk.strip() for chunk in content.split("\n\n") if chunk.strip()]

    if not chunks:
        logger.warning("没有读取到任何知识段落")
        return

    logger.info(f"读取到 {len(chunks)} 个知识段落")

    # 来源标记
    sources = [f"policies.txt_{i}" for i in range(len(chunks))]

    # 存入向量库
    vector_store.add(chunks, sources)

    logger.info(f"知识库加载完成，共 {vector_store.count()} 条记录")

    # 验证：搜索测试
    test_query = "年假怎么申请"
    results = vector_store.search(test_query, top_k=2)

    print("\n" + "=" * 50)
    print(f"[SEARCH] 搜索测试：{test_query}")
    print("=" * 50)

    if results:
        for i, r in enumerate(results, 1):
            print(f"\n【结果 {i}】来源: {r['source']}")
            print(f"内容: {r['text'][:80]}...")
            print(f"相似度: {r['score']:.4f}（距离: {r['distance']:.4f}）")
    else:
        print("没有找到相关结果")


if __name__ == "__main__":
    load_knowledge()
