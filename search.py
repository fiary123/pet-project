import os
import sys

# ==========================================
# 1. 网络环境清理 (和入库脚本保持一致)
# ==========================================
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com' # 确保模型能加载
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if key in os.environ:
        del os.environ[key]

import pg8000.dbapi
from sentence_transformers import SentenceTransformer

# ==========================================
# 2. 连接数据库 (使用正确的端口 5433)
# ==========================================
print("正在连接数据库...")
try:
    conn = pg8000.dbapi.connect(
        user="postgres",
        password="123456",  # 你的密码
        host="127.0.0.1",
        port=5433,          # 刚才改的端口
        database="postgres"
    )
    cursor = conn.cursor()
    print("✅ 数据库连接成功！")
except Exception as e:
    print(f"❌ 连接失败: {e}")
    exit()

# ==========================================
# 3. 加载 AI 模型
# ==========================================
print("正在加载 AI 模型 (clip-ViT-B-32)...")
model = SentenceTransformer('clip-ViT-B-32')

# ==========================================
# 4. 搜索主循环
# ==========================================
while True:
    print("\n" + "="*40)
    query_text = input("🔍 请输入你想找的宠物 (输入 'q' 退出): ").strip()
    
    if query_text.lower() == 'q':
        break
    
    if not query_text:
        continue

    print(f"正在寻找: '{query_text}' ...")
    
    # A. 把你的文字变成向量
    query_embedding = model.encode(query_text).tolist()
    
    # B. 在数据库里找最相似的图
    # <=> 是 pgvector 的专用符号，代表“计算距离”
    # ORDER BY ... ASC LIMIT 3 表示找距离最近(最像)的前3个
    sql = """
        SELECT name, image_url, description, 
               (image_embedding <=> %s) as distance 
        FROM pets 
        ORDER BY distance ASC 
        LIMIT 3
    """
    
    # 注意：pg8000 需要把向量转成字符串格式传入
    cursor.execute(sql, (str(query_embedding),))
    results = cursor.fetchall()
    
    # C. 打印结果
    if not results:
        print("没有找到匹配的宠物。")
    else:
        print(f"\n找到 {len(results)} 个匹配结果：")
        for idx, row in enumerate(results):
            # row[0]=name, row[1]=url, row[2]=desc, row[3]=distance
            score = 1 - float(row[3]) # 把距离转换成相似度分数 (越接近1越像)
            print(f"[{idx+1}] {row[0]} (相似度: {score:.2f})")
            print(f"    文件路径: {row[1]}")

conn.close()
print("👋 程序已退出")