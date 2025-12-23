import os
import sys
# ==========================================
# 【1】设置 Hugging Face 国内镜像 (解决模型下载失败)
# ==========================================
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

# ==========================================
# 【2】清理代理设置 (保护数据库连接)
# ==========================================
print("正在配置网络环境...")
# 必须先设置镜像，再清空代理。
# 这样模型下载走国内镜像(不需要代理)，数据库走本地(不需要代理)
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if key in os.environ:
        del os.environ[key]

# 2. 导入新驱动 pg8000
import pg8000.dbapi
import traceback
from sentence_transformers import SentenceTransformer
from PIL import Image

# 3. 连接数据库 (使用 pg8000)
print("\n正在尝试连接数据库 (pg8000 模式)...")
try:
    conn = pg8000.dbapi.connect(
        user="postgres",
        password="123456",
        host="127.0.0.1",
        port=5433,
        database="postgres"
    )
    conn.autocommit = True
    cursor = conn.cursor()
    print("✅ 数据库连接成功！(DLL冲突已解决)")
except Exception as e:
    print("\n❌ 连接失败！")
    traceback.print_exc()
    exit()

# 4. 加载 AI 模型
print("\n正在加载 AI 模型 (clip-ViT-B-32)...")
try:
    model = SentenceTransformer('clip-ViT-B-32')
except Exception as e:
    print(f"模型加载失败: {e}")
    exit()

# 5. 检查图片文件夹
image_folder = "./images"
if not os.path.exists(image_folder) or not os.listdir(image_folder):
    print(f"\n❌ 错误: '{image_folder}' 文件夹不存在或为空。")
    print("请在当前目录下创建 images 文件夹，并放入几张 .jpg 或 .png 图片。")
    exit()

# 6. 遍历图片并入库
valid_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
inserted_count = 0

print("\n🚀 开始处理图片...")
for filename in os.listdir(image_folder):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in valid_extensions:
        continue

    image_path = os.path.join(image_folder, filename)
    
    try:
        # A. 打开图片
        img = Image.open(image_path)
        
        # B. 生成向量
        embedding = model.encode(img).tolist()
        
        # 【关键修改】pg8000 对数组处理比较严格，我们直接转成字符串 "[0.1, ...]" 格式
        # 这样 pgvector 插件能完美识别
        embedding_str = str(embedding)
        
        # C. 构造数据
        pet_name = os.path.splitext(filename)[0]
        description = f"这是一只可爱的 {pet_name}"
        breed = "未知品种" 
        
        # D. 插入数据库
        sql = """
            INSERT INTO pets (name, breed, description, image_url, image_embedding)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (pet_name, breed, description, image_path, embedding_str))
        print(f"   [已存入] {filename}")
        inserted_count += 1
        
    except Exception as e:
        print(f"   [失败] 处理 {filename} 出错: {e}")

cursor.close()
conn.close()
print(f"\n🎉 全部完成！共存入 {inserted_count} 张宠物数据。")