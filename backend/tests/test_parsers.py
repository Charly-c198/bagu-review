from __future__ import annotations

from app.services.cleaning import clean_source_text
from app.services.import_parsers import (
    parse_content,
    parse_csv,
    parse_json,
    parse_markdown,
)
from app.utils.text import hamming_hex, normalize_text, simhash64


def test_normalize_and_simhash() -> None:
    assert normalize_text("  TCP   三次握手\r\n\r\n") == "TCP 三次握手"
    left = simhash64("TCP 三次握手的过程是什么")
    right = simhash64("TCP 三次握手过程是什么")
    far = simhash64("Docker 镜像与容器的区别")
    assert hamming_hex(left, right) < hamming_hex(left, far)
    assert len(left) == 16


MARKDOWN = """## 题目：TCP 为什么需要三次握手？
**答案**：两次握手无法确认客户端接收能力。
**要点**：确认收发能力；防止历史连接；资源分配
**标签**：TCP, 计算机网络
**难度**：3
**频率**：high
**公司**：腾讯,字节
**分类**：计算机网络/TCP

## 知识：TCP 三次握手
**类型**：process
**分类**：计算机网络/TCP
**别名**：三次握手,TCP 握手
**内容**：客户端发送 SYN，服务端返回 SYN-ACK，客户端再发送 ACK。
"""


def test_parse_markdown_question_and_knowledge() -> None:
    result = parse_markdown(MARKDOWN)
    assert len(result.questions) == 1
    assert len(result.knowledge) == 1
    question = result.questions[0]
    assert question.stem == normalize_text("TCP 为什么需要三次握手？")
    assert "两次握手" in question.answer
    assert question.key_points == ["确认收发能力", "防止历史连接", "资源分配"]
    assert question.tags == ["TCP", "计算机网络"]
    assert question.difficulty == 3
    assert question.frequency == "high"
    assert question.companies == ["腾讯", "字节"]
    assert question.category_path == ["计算机网络", "TCP"]
    knowledge = result.knowledge[0]
    assert knowledge.title == normalize_text("TCP 三次握手")
    assert knowledge.kind == "process"
    assert "SYN" in knowledge.content
    assert knowledge.aliases == ["三次握手", "TCP 握手"]


def test_parse_markdown_skips_code_fence_headings() -> None:
    text = """## 题目：代码题
```python
## 这不是新题目
print("hello")
```
**答案**：代码块中的标题不切分。
"""
    result = parse_markdown(text)
    assert len(result.questions) == 1
    question = result.questions[0]
    assert "## 这不是新题目" in question.stem
    assert question.answer == "代码块中的标题不切分。"


def test_parse_csv_partial_error() -> None:
    text = """stem,answer,key_points,category_path,tags,difficulty,frequency,companies
进程和线程的区别,资源单位不同,资源单位；调度单位,操作系统/进程管理,操作系统,2,high,阿里
坏行,答案,要点,操作系统/进程管理,操作系统,9,high,阿里
"""
    result = parse_csv(text)
    assert len(result.questions) == 1
    assert result.total_rows == 2
    assert len(result.errors) == 1
    assert result.errors[0]["record"] == 2
    assert "难度" in result.errors[0]["message"]


def test_parse_json_combined_links() -> None:
    text = """
    {
      "schema_version": 1,
      "questions": [
        {"stem": "什么是 RAG？", "answer": "检索增强生成", "key_points": ["检索", "生成"]}
      ],
      "knowledge": [
        {"ref": "kp-rag", "title": "RAG", "content": "检索增强生成的缩写", "kind": "concept"}
      ],
      "links": [
        {"question_index": 0, "knowledge_ref": "kp-rag", "relation_type": "related"}
      ]
    }
    """
    result = parse_json(text)
    assert len(result.questions) == 1
    assert len(result.knowledge) == 1
    assert result.knowledge[0].ref == "kp-rag"
    assert result.links == [
        {"question_index": 0, "knowledge_ref": "kp-rag", "relation_type": "related"}
    ]


def test_parse_markdown_thematic_break_and_extra_fields() -> None:
    """分隔线与未知 **字段** 不能污染上一个字段（真实面经常见写法）。"""
    text = """## 知识：TLS
**内容**：TLS 负责加密、身份认证与完整性校验。

---

## 题目：HTTPS 与 HTTP 的区别？
**答案**：HTTPS 多了 TLS 加密。
**频率**：high
**面试官**：追问了证书链

---

## 题目：第二题？
**答案**：第二题答案。
"""
    result = parse_markdown(text)
    assert [q.stem for q in result.questions] == [
        normalize_text("HTTPS 与 HTTP 的区别？"),
        normalize_text("第二题？"),
    ]
    assert result.questions[0].frequency == "high"
    assert "追问了证书链" in result.questions[0].notes
    assert result.errors == []
    assert len(result.knowledge) == 1
    assert "TLS" in result.knowledge[0].content


def test_parse_free_markdown_headings_and_interview_section() -> None:
    text = """# 分布式事务原理

## 面试题

分布式事务了解吗？你们是如何解决分布式事务问题的？

## 面试官心理分析

聊到分布式系统必问，答不上来很减分。

## 面试题剖析

主要有以下几种方案。

### 两阶段提交方案

所谓的 XA 方案即两阶段提交，由事务管理器协调多个数据库，属于强一致方案。

### TCC 方案

TCC 全称 Try、Confirm、Cancel，属于应用层补偿方案，适合高并发场景。
"""
    result = parse_markdown(text)
    stems = [q.stem for q in result.questions]
    assert any("分布式事务了解吗" in stem for stem in stems)
    assert any("如何解决分布式事务" in stem for stem in stems)
    titles = [k.title for k in result.knowledge]
    assert "两阶段提交方案" in titles
    assert "TCC 方案" in titles
    # 通用小节既不进题也不进知识。
    assert "面试题剖析" not in titles
    assert "面试官心理分析" not in titles
    assert all(q.confidence < 0.6 for q in result.questions)


def test_parse_free_markdown_question_heading_and_code_fence() -> None:
    text = """# 消息队列

## 如何保证消息队列的高可用？

常见做法是主从复制与镜像集群。

## 消费者幂等

```python
## 代码里的标题不算标题
def consume():
    pass
```

消费端需要做幂等处理，避免重复消费。
"""
    result = parse_markdown(text)
    question = result.questions[0]
    assert question.stem == normalize_text("如何保证消息队列的高可用？")
    assert "主从复制" in question.answer
    assert len(result.questions) == 1
    titles = [k.title for k in result.knowledge]
    assert "消费者幂等" in titles
    assert "代码里的标题不算标题" not in titles


def test_parse_content_dispatch() -> None:
    assert parse_content("md", MARKDOWN).questions
    assert parse_content("csv", "stem\n题\n").questions


def test_clean_source_text_preserves_line_numbers() -> None:
    text = """## 题目：TCP 三次握手
关注公众号领取资料
**答案**：三次握手确认双方收发能力。
"""
    cleaned, removed = clean_source_text(text)
    assert len(removed) == 1
    assert removed[0]["line"] == 2
    assert "关注公众号" not in cleaned
    assert cleaned.splitlines()[2].startswith("**答案**")
    result = parse_markdown(cleaned)
    assert len(result.questions) == 1
    assert result.questions[0].line == 1
    assert "三次握手确认" in result.questions[0].answer
