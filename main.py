import os
import shutil
import uuid
import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import pg8000.dbapi
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from PIL import Image

# ==========================================
# 🔐 安全与配置
# ==========================================
from passlib.context import CryptContext
from jose import JWTError, jwt

API_KEY = "sk-d4566f57108341a9b2f30c04293ac9b7" # 替换你的 DeepSeek Key
BASE_URL = "https://api.deepseek.com"
SECRET_KEY = "graduation_project_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# 环境清理
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if key in os.environ: del os.environ[key]

app = FastAPI(title="智能宠物生态系统 (Extended)", description="基于扩展研究报告重构：异步处理 + 社交 + 长期记忆")

# 工具初始化
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

os.makedirs("images", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/images", StaticFiles(directory="images"), name="images")
app.mount("/static", StaticFiles(directory="static"), name="static")

print("正在初始化多模态感知管道...")
try:
    # 报告 2.1.2: 视觉编码器，用于多模态数据处理
    clip_model = SentenceTransformer('clip-ViT-B-32') 
except: pass
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ==========================================
# 💾 数据库与模型
# ==========================================
def get_db_connection():
    return pg8000.dbapi.connect(user="postgres", password="123456", host="127.0.0.1", port=5433, database="postgres")

def init_comments_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            post_id INTEGER REFERENCES social_posts(id),
            user_id INTEGER REFERENCES users(id),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# Initialize DB tables
try:
    init_comments_table()
except Exception as e:
    print(f"Warning: Could not initialize comments table: {e}")

# Pydantic Models
class UserRegister(BaseModel):
    email: str; password: str; username: str; role: str = "user"

class Token(BaseModel):
    access_token: str; token_type: str

class ChatRequest(BaseModel):
    pet_id: int; user_msg: str

class PostResult(BaseModel):
    id: int; username: str; content: str; image_url: str; likes: int

class CommentRequest(BaseModel):
    content: str

class CommentResult(BaseModel):
    id: int; username: str; content: str

class PetSearchRequest(BaseModel):
    query: str

class PetSearchResult(BaseModel):
    id: int; name: str; breed: str; description: str; image_url: str; score: float

# ==========================================
# 🧠 核心逻辑函数 (包含异步任务)
# ==========================================

# 1. 安全函数 (保持不变)
def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)
def create_access_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"id": payload.get("id"), "email": payload.get("sub"), "role": payload.get("role")}
    except JWTError:
        raise HTTPException(status_code=401, detail="无效凭证")

# 2. 异步图像处理任务 (对应报告 2.1.1 异步任务编排)
# 将耗时的向量化操作放入后台，防止阻塞主线程
def process_image_embedding_task(file_path: str, table_name: str, record_id: int):
    print(f"🔄 [后台任务] 开始处理图片向量: {file_path}")
    try:
        img = Image.open(file_path)
        embedding = clip_model.encode(img).tolist()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        # 动态更新表中的向量字段
        if table_name == "pets":
            cursor.execute("UPDATE pets SET image_embedding = %s WHERE id = %s", (str(embedding), record_id))
        elif table_name == "social_posts":
            cursor.execute("UPDATE social_posts SET image_embedding = %s WHERE id = %s", (str(embedding), record_id))
        
        conn.commit()
        conn.close()
        print(f"✅ [后台任务] 向量计算完成，已更新 ID: {record_id}")
    except Exception as e:
        print(f"❌ [后台任务] 失败: {e}")

# ==========================================
# 🌐 API 接口
# ==========================================

@app.get("/")
async def read_index(): return FileResponse('static/index.html')

# --- 🔐 认证模块 ---
@app.post("/auth/register")
async def register(user: UserRegister):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        hashed = get_password_hash(user.password)
        cursor.execute("INSERT INTO users (email, username, hashed_password, role) VALUES (%s, %s, %s, %s) RETURNING id", 
                       (user.email, user.username, hashed, user.role))
        conn.commit()
        return {"msg": "注册成功"}
    except Exception as e:
        return {"msg": f"注册失败: {e}"}
    finally: conn.close()

@app.post("/auth/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, hashed_password, role FROM users WHERE email = %s", (form_data.username,))
    user = cursor.fetchone()
    conn.close()
    
    if not user or not verify_password(form_data.password, user[2]):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    
    token = create_access_token({"sub": user[1], "id": user[0], "role": user[3]})
    return {"access_token": token, "token_type": "bearer"}

# --- 📱 社交与发布模块 (对应报告 3.1) ---

@app.post("/social/post")
async def create_post(
    background_tasks: BackgroundTasks, # FastAPI 原生异步支持
    content: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    # 1. 存图
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"images/{filename}"
    with open(path, "wb") as f: shutil.copyfileobj(file.file, f)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 2. 写入数据库 (先不存向量，提高响应速度)
    cursor.execute(
        "INSERT INTO social_posts (user_id, content, image_url) VALUES (%s, %s, %s) RETURNING id",
        (current_user['id'], content, f"./images/{filename}")
    )
    post_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    
    # 3. 【异步】触发后台向量化任务
    background_tasks.add_task(process_image_embedding_task, path, "social_posts", post_id)
    
    return {"status": "posted", "post_id": post_id, "msg": "发布成功，正在后台处理AI分析..."}

@app.get("/social/feed", response_model=List[PostResult])
async def get_feed(current_user: dict = Depends(get_current_user)):
    """
    智能推荐流：这里实现了报告 3.1.2 的逻辑。
    目前简化为按时间倒序，未来可加入 pgvector 余弦相似度排序。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, u.username, p.content, p.image_url, p.likes_count 
        FROM social_posts p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC LIMIT 10
    """)
    results = cursor.fetchall()
    conn.close()
    return [PostResult(id=r[0], username=r[1], content=r[2], image_url=r[3], likes=r[4]) for r in results]

@app.post("/social/posts/{post_id}/comments")
async def add_comment(post_id: int, comment: CommentRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO comments (post_id, user_id, content) VALUES (%s, %s, %s) RETURNING id",
        (post_id, current_user['id'], comment.content)
    )
    comment_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return {"status": "success", "comment_id": comment_id}

@app.get("/social/posts/{post_id}/comments", response_model=List[CommentResult])
async def get_comments(post_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, u.username, c.content 
        FROM comments c 
        JOIN users u ON c.user_id = u.id 
        WHERE c.post_id = %s 
        ORDER BY c.created_at ASC
    """, (post_id,))
    results = cursor.fetchall()
    conn.close()
    return [CommentResult(id=r[0], username=r[1], content=r[2]) for r in results]

# --- 💬 数字孪生聊天 (含长期记忆) ---
@app.post("/chat")
async def chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 获取人设
    cursor.execute("SELECT system_prompt, name FROM pets p JOIN personas per ON p.id = per.pet_id WHERE p.id = %s", (req.pet_id,))
    res = cursor.fetchone()
    sys_prompt = res[0] if res else "你是宠物"
    pet_name = res[1] if res else "未知"

    # 2. 【长期记忆检索】(RAG)
    # 对应报告 5.1: 检索与当前对话相关的长期记忆
    # 简化版：暂时只获取最近的记忆，实际应使用向量检索
    cursor.execute("SELECT memory_text FROM long_term_memories WHERE pet_id = %s ORDER BY created_at DESC LIMIT 2", (req.pet_id,))
    memories = cursor.fetchall()
    memory_context = "\n".join([f"- {m[0]}" for m in memories])
    
    # 注入记忆到 Prompt
    full_system_prompt = f"{sys_prompt}\n\n【你需要记住的事实】:\n{memory_context}"

    # 3. 调用 LLM
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": req.user_msg}
            ]
        )
        reply = response.choices[0].message.content
        
        # 4. 存入交互历史
        cursor.execute("INSERT INTO interactions (user_id, pet_id, user_msg, ai_reply) VALUES (%s, %s, %s, %s)",
                       (current_user['id'], req.pet_id, req.user_msg, reply))
        
        # 5. 【记忆形成】(简单模拟)
        # 如果回复比较长，或者包含特定关键词，我们假设这是一个值得记住的时刻
        # 实际应由另一个 LLM Agent 分析提取
        if len(req.user_msg) > 10: 
            cursor.execute("INSERT INTO long_term_memories (pet_id, memory_text) VALUES (%s, %s)", 
                           (req.pet_id, f"用户说: {req.user_msg}"))

        conn.commit()
        return {"reply": reply, "pet_name": pet_name}
    except Exception as e:
        print(e)
        return {"reply": "汪...我累了"}
    finally:
        conn.close()

# --- 🐾 管理员发布 (异步版) ---
@app.post("/publish")
async def publish_pet(
    background_tasks: BackgroundTasks, # 异步处理
    name: str = Form(...), breed: str = Form(...), description: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    if current_user['role'] != 'admin': raise HTTPException(403, "权限不足")
    
    # 1. 存图
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"images/{filename}"
    with open(path, "wb") as f: shutil.copyfileobj(file.file, f)

    # 2. 存库 (image_embedding 暂时为空)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO pets (name, breed, description, image_url) VALUES (%s, %s, %s, %s) RETURNING id",
        (name, breed, description, f"./images/{filename}")
    )
    pet_id = cursor.fetchone()[0]
    
    # 3. 初始化人设
    cursor.execute("INSERT INTO personas (pet_id, system_prompt) VALUES (%s, %s)", 
                   (pet_id, f"你是一只{breed}，名字叫{name}。{description}"))
    conn.commit()
    conn.close()

    # 4. 【异步】后台生成向量
    background_tasks.add_task(process_image_embedding_task, path, "pets", pet_id)

    return {"status": "success", "pet_id": pet_id, "msg": "宠物发布成功，AI 正在后台学习它的照片..."}

@app.get("/pets/initial", response_model=List[PetSearchResult])
async def get_initial_pets():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, breed, description, image_url FROM pets ORDER BY id DESC LIMIT 6")
    results = cursor.fetchall()
    conn.close()
    return [PetSearchResult(id=r[0], name=r[1], breed=r[2], description=r[3], image_url=r[4], score=1.0) for r in results]

@app.post("/search", response_model=List[PetSearchResult])
async def search_pets_api(req: PetSearchRequest):
    # 1. 把你的文字变成向量
    try:
        query_embedding = clip_model.encode(req.query).tolist()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI模型向量化失败: {e}")
    
    # 2. 在数据库里找最相似的图
    conn = get_db_connection()
    cursor = conn.cursor()
    # <=> 是 pgvector 的专用符号，代表“计算距离”
    sql = """
        SELECT id, name, breed, description, image_url,
               (image_embedding <=> %s) as distance 
        FROM pets 
        ORDER BY distance ASC 
        LIMIT 6
    """
    cursor.execute(sql, (str(query_embedding),))
    results = cursor.fetchall()
    conn.close()
    
    return [
        PetSearchResult(
            id=r[0], name=r[1], breed=r[2], description=r[3], image_url=r[4], 
            score=round(1 - float(r[5]), 2) if r[5] is not None else 0.0
        ) for r in results
    ]