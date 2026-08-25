# -*- coding: utf-8 -*-
"""use_container_width 파라미터를 width='stretch'/'content'로 일괄 교체"""

with open('app.py', encoding='utf-8') as f:
    content = f.read()

original_count = content.count('use_container_width')
print(f"교체 전 use_container_width 개수: {original_count}")

# 순서 중요: 더 구체적인 패턴부터 교체
content = content.replace(", use_container_width=True)", ", width='stretch')")
content = content.replace(", use_container_width=True,", ", width='stretch',")
content = content.replace("use_container_width=True,", "width='stretch',")
content = content.replace("use_container_width=True)", "width='stretch')")
content = content.replace(", use_container_width=False)", ", width='content')")
content = content.replace(", use_container_width=False,", ", width='content',")
content = content.replace("use_container_width=False,", "width='content',")
content = content.replace("use_container_width=False)", "width='content')")
# None 패턴도 처리
content = content.replace(", use_container_width=None)", ")")
content = content.replace(", use_container_width=None,", ",")

remaining = content.count('use_container_width')
print(f"교체 후 남은 use_container_width 개수: {remaining}")
print(f"width='stretch' 개수: {content.count(chr(39) + 'stretch' + chr(39))}")

# 문법 검증
import ast
try:
    ast.parse(content)
    print("AST PARSE SUCCESS")
except SyntaxError as e:
    print(f"SyntaxError: {e}")
    exit(1)

with open('app.py', 'w', encoding='utf-8', newline='') as f:
    f.write(content)
print("저장 완료!")
