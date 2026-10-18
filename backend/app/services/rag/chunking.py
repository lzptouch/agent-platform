"""文本切块：保持段落和表格完整性（源自 notebook 的 chunk_text）。"""


def chunk_text(text: str, max_chunk_size: int = 300) -> list[str]:
    """
    将文本切分成固定大小的块，保持段落和表格的完整性。

    Args:
        text: 需要切分的文本
        max_chunk_size: 每个块的最大大小，默认 300

    Returns:
        包含切分后文本块的列表
    """
    lines = text.split("\n")

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_size = 0
    in_table = False
    table_content: list[str] = []

    for line in lines:
        # 检测表格开始（含有 | 字符的行，通常是表格）
        if "|" in line and not in_table:
            in_table = True
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            table_content.append(line)

        # 表格内容
        elif in_table:
            table_content.append(line)
            if not line.strip():
                in_table = False
                chunks.append("\n".join(table_content))
                table_content = []

        # 普通内容
        else:
            line_length = len(line)
            if current_size + line_length > max_chunk_size and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0

            current_chunk.append(line)
            current_size += line_length

            if not line.strip() and current_size > max_chunk_size // 2:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0

    if in_table and table_content:
        chunks.append("\n".join(table_content))
    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return [c for c in chunks if c.strip()]
